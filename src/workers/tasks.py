"""
Background Tasks
================

Celery tasks for background document processing.
"""

import asyncio
import logging
import sys

# Ensure custom packages are loadable
if "/app/.packages" not in sys.path:
    sys.path.insert(0, "/app/.packages")

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.ingestion.domain.chunk import Chunk
from src.core.state.machine import DocumentStatus
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery task."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Prevent "Cannot run the event loop while another loop is running"
        # by offloading the async execution to a separate thread with its own loop.
        print(f"DEBUG: Detected running loop {loop}, offloading to thread for coro: {coro}")
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            def runner():
                print("DEBUG: Thread started, running asyncio.run")
                try:
                    res = asyncio.run(coro)
                    print("DEBUG: asyncio.run completed")
                    return res
                except Exception as e:
                    print(f"DEBUG: Thread failed: {e}")
                    raise
            
            future = executor.submit(runner)
            print("DEBUG: Waiting for thread result...")
            res = future.result()
            print("DEBUG: Thread result received")
            return res
    else:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


class BaseTask(Task):
    """Base task with common error handling."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300  # 5 minutes max
    retry_jitter = True
    max_retries = 3


@celery_app.task(bind=True, name="src.workers.tasks.health_check")
def health_check(self) -> dict:
    """
    Simple health check task for worker verification.

    Returns:
        dict: Health check result
    """
    return {
        "status": "healthy",
        "worker_id": self.request.id,
        "task": "health_check",
    }


@celery_app.task(
    bind=True,
    name="src.workers.tasks.process_document",
    base=BaseTask,
    max_retries=3,
    default_retry_delay=60
)
def process_document(self, document_id: str, tenant_id: str) -> dict:
    """
    Process a document through the full ingestion pipeline.

    Steps:
    1. Fetch document from DB
    2. Update status to EXTRACTING
    3. Run extraction (FallbackManager)
    4. Update status to CLASSIFYING
    5. Run domain classification
    6. Update status to CHUNKING
    7. Run semantic chunking
    8. Update status to READY

    Args:
        document_id: ID of the document to process.
        tenant_id: Tenant for context.

    Returns:
        dict: Processing result summary.
    """
    logger.info(f"[Task {self.request.id}] Starting processing for document {document_id}")

    try:
        result = run_async(_process_document_async(document_id, tenant_id, self.request.id))
        logger.info(f"[Task {self.request.id}] Completed processing for document {document_id}")

        # Trigger community detection asynchronously
        try:
            logger.info(f"[Task {self.request.id}] Triggering community detection for tenant {tenant_id}")
            process_communities.delay(tenant_id)
        except Exception as e:
            logger.warning(f"Failed to trigger community detection: {e}")

        return result

    except Exception as e:
        import traceback
        logger.error(f"[Task {self.request.id}] Failed processing document {document_id}: {e}\n{traceback.format_exc()}")

        # Update document status to FAILED
        try:
            run_async(_mark_document_failed(document_id, str(e)))
        except Exception as fail_err:
            logger.error(f"Failed to mark document as failed: {fail_err}")

        # Retry if not exceeded
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error(f"[Task {self.request.id}] Max retries exceeded for document {document_id}")
            raise


@celery_app.task(
    bind=True,
    name="src.workers.tasks.process_communities",
    base=BaseTask,
    max_retries=2
)
def process_communities(self, tenant_id: str) -> dict:
    """
    Periodic or triggered task to update graph communities and summaries.
    """
    logger.info(f"[Task {self.request.id}] Updating communities for tenant {tenant_id}")
    try:
        result = run_async(_process_communities_async(tenant_id))
        return result
    except Exception as e:
        logger.error(f"Community processing failed: {e}")
        raise self.retry(exc=e) from e


async def _process_communities_async(tenant_id: str) -> dict:
    """Async implementation of community processing."""
    from src.amber_platform.composition_root import build_vector_store_factory, platform
    from src.api.config import settings
    from src.core.graph.application.communities.embeddings import CommunityEmbeddingService
    from src.core.graph.application.communities.leiden import CommunityDetector
    from src.core.graph.application.communities.summarizer import CommunitySummarizer
    from src.core.generation.infrastructure.providers.factory import ProviderFactory
    from src.core.retrieval.application.embeddings_service import EmbeddingService
    from src.core.admin_ops.application.tuning_service import TuningService
    from src.core.database.session import async_session_maker

    try:
        # 1. Detection
        detector = CommunityDetector(platform.neo4j_client)
        detect_res = await detector.detect_communities(tenant_id)

        if detect_res["status"] == "skipped":
            return detect_res

        # 2. Summarization
        factory = ProviderFactory(
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=settings.anthropic_api_key
        )
        summarizer = CommunitySummarizer(platform.neo4j_client, factory)
        tuning_service = TuningService(async_session_maker)
        tenant_config = await tuning_service.get_tenant_config(tenant_id)

        # We summarize all that are now stale or new
        await summarizer.summarize_all_stale(tenant_id, tenant_config=tenant_config)

        # 3. Embeddings
        embedding_svc = EmbeddingService(
            openai_api_key=settings.openai_api_key,
            model=settings.embeddings.default_model if hasattr(settings, 'embeddings') else "text-embedding-3-small"
        )
        vector_store_factory = build_vector_store_factory()
        comm_vector_store = vector_store_factory(
            settings.embedding_dimensions or 1536,
            collection_name="community_embeddings",
        )
        comm_embedding_svc = CommunityEmbeddingService(
            embedding_service=embedding_svc,
            vector_store=comm_vector_store,
        )

        # Fetch all communities that need embedding (just summarized)
        # Actually, we can just fetch all 'ready' communities for this tenant for now
        # or track which ones were just updated.
        # For MVP, we'll re-sync all 'ready' communities to Milvus.
        query = """
        MATCH (c:Community {tenant_id: $tenant_id, status: 'ready'})
        RETURN c.id as id, c.tenant_id as tenant_id, c.level as level, c.title as title, c.summary as summary
        """
        ready_comms = await platform.neo4j_client.execute_read(query, {"tenant_id": tenant_id})

        for comm in ready_comms:
            await comm_embedding_svc.embed_and_store_community(comm)

        return {
            "status": "success",
            "communities_detected": detect_res.get("community_count", 0),
            "communities_embedded": len(ready_comms)
        }
    finally:
        # Close Neo4j connection to prevent event loop conflicts
        try:
            await platform.neo4j_client.close()
        except Exception as e:
            logger.warning(f"Failed to close Neo4j client: {e}")


def deep_reset_singletons():
    """
    Force reset of all singleton instances that might capture the event loop
    or hold stale connections. Critical for CELERY_TASK_ALWAYS_EAGER=True.
    """
    from src.core.database.session import reset_engine
    from src.core.generation.infrastructure.providers import factory
    from src.amber_platform.composition_root import platform

    logger.info("Executing deep reset of singletons for background task isolation")
    
    # 1. SQLAlchemy Engine & Pool
    reset_engine()
    
    # 2. Provider Factory (Reset cached providers and usage trackers)
    factory._default_factory = None
    
    # 3. Platform Clients (Neo4j, Redis, etc)
    # Force reset platform state to ensure fresh clients in this process/loop.
    # This is critical because if the parent process initialized these, the forked
    # worker process inherits them but cannot use the parent's asyncio loop/driver.
    platform._neo4j_client = None
    platform._minio_client = None
    platform._redis_client = None
    platform._graph_extractor = None 
    platform._content_extractor = None
    platform._initialized = False

    logger.info("Platform registry singletons reset.")

async def _process_document_async(document_id: str, tenant_id: str, task_id: str) -> dict:
    """
    Async implementation of document processing.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.amber_platform.composition_root import platform, build_vector_store_factory
    from src.api.config import settings
    # Context isolation: Reset EVERYTHING that might be stale or bound to a closed loop
    deep_reset_singletons()

    from src.amber_platform.composition_root import configure_settings
    configure_settings(settings)

    from src.core.database.session import configure_database
    configure_database(settings.db.database_url)

    from src.shared.kernel.runtime import configure_settings as configure_runtime_settings
    configure_runtime_settings(settings)

    from src.core.generation.infrastructure.providers.factory import init_providers
    init_providers(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
        ollama_base_url=settings.ollama_base_url,
    )

    from src.core.graph.domain.ports.graph_extractor import set_graph_extractor
    from src.core.ingestion.infrastructure.extraction.graph_extractor import GraphExtractor
    set_graph_extractor(GraphExtractor(use_gleaning=True))

    # Create async session
    engine = create_async_engine(settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # Initialize services
            from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
            from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import PostgresTenantRepository
            from src.core.ingestion.infrastructure.uow.postgres_uow import PostgresUnitOfWork
            from src.core.ingestion.application.ingestion_service import IngestionService
            from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
            from src.core.tenants.domain.tenant import Tenant
            from src.core.events.dispatcher import EventDispatcher
            from src.infrastructure.adapters.redis_state_publisher import RedisStatePublisher
            
            vector_store_factory = build_vector_store_factory()
            event_dispatcher = EventDispatcher(RedisStatePublisher())
            
            repo = PostgresDocumentRepository(session)
            tenant_repo = PostgresTenantRepository(session)
            uow = PostgresUnitOfWork(session)
            
            # Validation
            document = await repo.get(document_id)
            if not document:
                 raise ValueError(f"Document {document_id} not found")
            
            service = IngestionService(
                document_repository=repo,
                tenant_repository=tenant_repo,
                unit_of_work=uow,
                storage_client=platform.minio_client,
                neo4j_client=platform.neo4j_client,
                vector_store=None,
                settings=settings,
                event_dispatcher=event_dispatcher,
                vector_store_factory=vector_store_factory,
            )

            # Publish starting event
            _publish_status(document_id, DocumentStatus.EXTRACTING.value, 10)

            # Process document (this does extraction, classification, chunking)
            await service.process_document(document_id)

            # Refresh to get final state
            document = await repo.get(document_id)

            # Publish completion
            _publish_status(document_id, document.status.value, 100)

            # Get chunk count for stats
            from src.core.ingestion.domain.chunk import Chunk
            chunk_result = await session.execute(
                select(Chunk).where(Chunk.document_id == document_id)
            )
            chunks = chunk_result.scalars().all()

            return {
                "document_id": document_id,
                "status": document.status.value,
                "domain": document.domain,
                "chunk_count": len(chunks),
                "task_id": task_id
            }
    finally:
        # Close Neo4j connection before disposing engine
        # This prevents "attached to a different loop" errors
        try:
            await platform.neo4j_client.close()
        except Exception as e:
            logger.warning(f"Failed to close Neo4j client: {e}")

        await engine.dispose()


async def _mark_document_failed(document_id: str, error: str):
    """Mark document as failed in DB."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings

    engine = create_async_engine(settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            result = await session.execute(select(Document).where(Document.id == document_id))
            document = result.scalars().first()

            if document:
                document.status = DocumentStatus.FAILED
                await session.commit()
                _publish_status(document_id, DocumentStatus.FAILED.value, 100, error=error)
    finally:
        await engine.dispose()


def _publish_status(document_id: str, status: str, progress: int, error: str = None):
    """Publish status update to Redis Pub/Sub."""
    import json
    try:
        import redis

        from src.api.config import settings

        r = redis.Redis.from_url(settings.db.redis_url)
        try:
            channel = f"document:{document_id}:status"
            message = {
                "document_id": document_id,
                "status": status,
                "progress": progress
            }
            if error:
                message["error"] = error

            r.publish(channel, json.dumps(message))
        finally:
            r.close()
    except Exception as e:
        logger.warning(f"Failed to publish status: {e}")


def _publish_benchmark_status(benchmark_id: str, status: str, progress: int, error: str = None):
    """Publish benchmark status update to Redis Pub/Sub."""
    import json
    try:
        import redis

        from src.api.config import settings

        r = redis.Redis.from_url(settings.db.redis_url)
        channel = f"benchmark:{benchmark_id}:status"
        message = {
            "benchmark_id": benchmark_id,
            "status": status,
            "progress": progress
        }
        if error:
            message["error"] = error

        r.publish(channel, json.dumps(message))
        r.close()
    except Exception as e:
        logger.warning(f"Failed to publish benchmark status: {e}")


@celery_app.task(
    bind=True,
    name="src.workers.tasks.run_ragas_benchmark",
    base=BaseTask,
    max_retries=1
)
def run_ragas_benchmark(self, benchmark_run_id: str, tenant_id: str) -> dict:
    """
    Execute a Ragas benchmark run.

    Steps:
    1. Fetch BenchmarkRun from DB
    2. Update status to RUNNING
    3. Load the golden dataset
    4. For each sample, run the RAG pipeline and evaluate with RagasService
    5. Aggregate results and store in DB
    6. Update status to COMPLETED

    Args:
        benchmark_run_id: ID of the BenchmarkRun to execute
        tenant_id: Tenant context

    Returns:
        dict: Benchmark result summary
    """
    logger.info(f"[Task {self.request.id}] Starting benchmark run {benchmark_run_id}")

    try:
        result = run_async(_run_ragas_benchmark_async(benchmark_run_id, tenant_id, self.request.id))
        logger.info(f"[Task {self.request.id}] Completed benchmark run {benchmark_run_id}")
        return result

    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed benchmark run {benchmark_run_id}: {e}")

        # Update benchmark status to FAILED
        try:
            run_async(_mark_benchmark_failed(benchmark_run_id, str(e)))
        except Exception as fail_err:
            logger.error(f"Failed to mark benchmark as failed: {fail_err}")

        raise


async def _run_ragas_benchmark_async(benchmark_run_id: str, tenant_id: str, task_id: str) -> dict:
    """Async implementation of Ragas benchmark execution."""
    import json
    from datetime import datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    # Defer heavy imports to after status update
    # from src.core.admin_ops.application.evaluation.ragas_service import RagasService
    from src.core.admin_ops.domain.benchmark_run import BenchmarkRun, BenchmarkStatus

    # Create async session
    engine = create_async_engine(settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # Fetch benchmark run
            result = await session.execute(
                select(BenchmarkRun).where(BenchmarkRun.id == benchmark_run_id)
            )
            benchmark = result.scalars().first()

            if not benchmark:
                raise ValueError(f"BenchmarkRun {benchmark_run_id} not found")

            # Update status to RUNNING
            benchmark.status = BenchmarkStatus.RUNNING
            benchmark.started_at = datetime.utcnow()
            benchmark.metrics = {"progress": 5}
            await session.commit()
            _publish_benchmark_status(benchmark_run_id, "running", 5)

            # Load golden dataset
            # 1. Try uploads dir
            # 2. Try src/core/evaluation
            # 3. Try tests/data
            
            # Note: We need to handle potential path persistence issues.
            # Ideally benchmark.dataset_name is just the filename.
            
            potential_paths = [
                f"/app/uploads/datasets/{benchmark.dataset_name}",
                f"src/core/evaluation/{benchmark.dataset_name}",
                f"tests/data/{benchmark.dataset_name}"
            ]
            
            dataset = None
            for p in potential_paths:
                try:
                    with open(p) as f:
                        dataset = json.load(f)
                    logger.info(f"Loaded dataset from {p}")
                    break
                except FileNotFoundError:
                    continue
                    
            if not dataset:
                 raise FileNotFoundError(f"Dataset {benchmark.dataset_name} not found in any search path")
            
            # Update progress: Dataset loaded
            benchmark.metrics = {"progress": 10}
            await session.commit()
            _publish_benchmark_status(benchmark_run_id, "running", 10)

            # Initialize RAG Services
            from src.core.generation.application.generation_service import GenerationService
            from src.core.retrieval.application.retrieval_service import RetrievalConfig, RetrievalService
            from openai import AsyncOpenAI
            from src.core.admin_ops.application.evaluation.ragas_service import RagasService
            
            # Initialize Ragas
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            ragas_service = RagasService(llm_client=client)

            # Initialize RAG Pipeline
            retrieval_config = RetrievalConfig(
                milvus_host=settings.db.milvus_host,
                milvus_port=settings.db.milvus_port,
            )
            retrieval_service = RetrievalService(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key,
                redis_url=settings.db.redis_url,
                config=retrieval_config,
            )
            generation_service = GenerationService(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key,
            )

            # Update progress: Services initialized
            benchmark.metrics = {"progress": 15}
            await session.commit()
            _publish_benchmark_status(benchmark_run_id, "running", 15)

            # Run evaluation on each sample
            details = []
            total_samples = len(dataset)
            
            logger.info(f"Starting benchmark execution for {total_samples} samples...")

            for i, sample in enumerate(dataset):
                query = sample.get("query", sample.get("question", ""))
                
                # Check mapping for standard Ragas keys
                ground_truth = sample.get("ground_truth", sample.get("ideal_answer", sample.get("answer", "")))

                # 1. Execute Retrieval
                retrieval_result = await retrieval_service.retrieve(
                    query=query,
                    tenant_id=tenant_id,
                    top_k=5
                )
                
                # 2. Execute Generation
                if retrieval_result.chunks:
                    gen_result = await generation_service.generate(
                        query=query,
                        candidates=retrieval_result.chunks
                    )
                    generated_answer = gen_result.answer
                    retrieved_contexts = [c.get("content", "") for c in retrieval_result.chunks]
                else:
                    generated_answer = "I couldn't find any relevant information."
                    retrieved_contexts = []

                logger.info(f"Processing Sample {i+1}/{total_samples} - Query: {query[:30]}...")
                
                # Evaluate using RagasService
                # Pass GENERATED answer and RETRIEVED contexts (this is the real benchmark)
                eval_result = await ragas_service.evaluate_sample(
                    query=query,
                    context=retrieved_contexts, # Pass list of strings
                    response=generated_answer
                )

                import math
                def clean_score(score):
                    if score is None:
                        return None
                    if isinstance(score, float) and (math.isnan(score) or math.isinf(score)):
                        return None
                    return score

                details.append({
                    "query": query,
                    "faithfulness": clean_score(eval_result.faithfulness),
                    "response_relevancy": clean_score(eval_result.response_relevancy),
                    "context_precision": clean_score(eval_result.context_precision),
                    "context_recall": clean_score(eval_result.context_recall)
                })

                # Publish progress (Scale 15% to 100%)
                metrics_progress = 15 + int((i + 1) / total_samples * 85)
                _publish_benchmark_status(benchmark_run_id, "running", metrics_progress)
                
                # Update progress in DB for polling UI
                benchmark.metrics = {"progress": metrics_progress}
                await session.commit()

            # Aggregate metrics
            faith_scores = [d["faithfulness"] for d in details if d["faithfulness"] is not None]
            rel_scores = [d["response_relevancy"] for d in details if d["response_relevancy"] is not None]
            
            metrics = {
                "faithfulness": sum(faith_scores) / len(faith_scores) if faith_scores else 0.0,
                "response_relevancy": sum(rel_scores) / len(rel_scores) if rel_scores else 0.0,
                "samples_evaluated": len(details)
            }

            # Update benchmark with results
            benchmark.status = BenchmarkStatus.COMPLETED
            benchmark.completed_at = datetime.utcnow()
            benchmark.metrics = metrics
            benchmark.details = details
            await session.commit()

            _publish_benchmark_status(benchmark_run_id, "completed", 100)

            return {
                "benchmark_run_id": benchmark_run_id,
                "status": "completed",
                "metrics": metrics,
                "samples_evaluated": len(details),
                "task_id": task_id
            }
    finally:
        await engine.dispose()


async def _mark_benchmark_failed(benchmark_run_id: str, error: str):
    """Mark benchmark as failed in DB."""
    from datetime import datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    from src.core.admin_ops.domain.benchmark_run import BenchmarkRun, BenchmarkStatus

    engine = create_async_engine(settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            result = await session.execute(
                select(BenchmarkRun).where(BenchmarkRun.id == benchmark_run_id)
            )
            benchmark = result.scalars().first()

            if benchmark:
                benchmark.status = BenchmarkStatus.FAILED
                benchmark.completed_at = datetime.utcnow()
                benchmark.error_message = error
                await session.commit()
                _publish_benchmark_status(benchmark_run_id, "failed", 100, error=error)
    finally:
        await engine.dispose()
