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

from src.core.ingestion.domain.chunk import (
    Chunk as _Chunk,  # noqa: F401 — ensures SQLAlchemy mapper resolves Document.chunks at runtime
)
from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_COMMUNITY_RESUME_PHASES = frozenset({"detection", "summarization", "embedding"})


class CommunityPhaseError(RuntimeError):
    def __init__(self, resume_from: str, cause: Exception):
        super().__init__(str(cause))
        self.resume_from = resume_from


def _is_revoked(task_id: str) -> bool:
    """
    Return True if the given Celery task has been revoked.

    Checks the result-backend state (Redis).  Falls back to False on any error
    so that a transient Redis hiccup never silently aborts work.
    """
    try:
        from celery.result import AsyncResult

        state = AsyncResult(task_id, app=celery_app).state
        return state == "REVOKED"
    except Exception as exc:
        logger.warning(f"[Task {task_id}] revocation check failed (ignoring): {exc}")
        return False


def _background_warmup():
    """Run heavy model warming in a background thread."""
    try:
        logger.info("Starting background warmup for SparseEmbeddingService (SPLADE)...")
        from src.core.retrieval.application.sparse_embeddings_service import SparseEmbeddingService

        service = SparseEmbeddingService()
        if service.prewarm():
            logger.info("SparseEmbeddingService background warmup completed.")
        else:
            logger.warning("SparseEmbeddingService background warmup returned False.")
    except Exception as e:
        logger.error(f"Failed to background warmup SparseEmbeddingService: {e}")


# Trigger background warmup on module load (worker startup)
# threading.Thread(target=_background_warmup, daemon=True).start()


def run_async(coro):
    """Helper to run async code in sync Celery task."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Prevent "Cannot run the event loop while another loop is running"
        # by offloading the async execution to a separate thread with its own loop.
        logger.debug(
            "Detected active event loop %s, offloading coroutine execution to a worker thread",
            loop,
        )
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

            def runner():
                logger.debug("Worker thread started for asyncio.run")
                try:
                    res = asyncio.run(coro)
                    logger.debug("Worker thread completed asyncio.run")
                    return res
                except Exception as e:
                    logger.debug("Worker thread failed while running coroutine: %s", e)
                    raise

            future = executor.submit(runner)
            logger.debug("Waiting for worker thread result")
            res = future.result()
            logger.debug("Worker thread result received")
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
    default_retry_delay=60,
    queue="high_priority",
)
def process_document(self, document_id: str, tenant_id: str) -> dict:
    """
    Process a document through the full ingestion pipeline.

    Steps:
    1. Fetch document from DB
    2. Transition status INGESTED -> EXTRACTING
    3. Get file from storage
    4. Extract content (FallbackManager / mime-type detection)
    4b. Quality gate — if thresholds breached, transition to NEEDS_REVIEW and stop
    5. Transition to CLASSIFYING; run domain classification
    6. Transition to CHUNKING; run semantic chunking
    7. Transition to EMBEDDING; generate dense + sparse embeddings, upsert to Milvus,
       write Chunk nodes to Neo4j, build similarity edges
    8. Transition to GRAPH_SYNC; extract entities/relationships and build knowledge graph
    9. Document enrichment: summary, document_type, hashtags, keywords via LLM
    10. Transition to READY; invalidate result cache

    After the pipeline, triggers community detection/update (incremental if communities
    already exist, full Leiden if first ingestion) — deferred when other docs are in flight.

    Args:
        document_id: ID of the document to process.
        tenant_id: Tenant for context.

    Returns:
        dict: Processing result summary.
    """
    logger.info(f"[Task {self.request.id}] Starting processing for document {document_id}")

    # Cooperative cancellation: bail out before starting expensive work if the
    # task was already revoked (e.g. cancel called while task was in the queue).
    if _is_revoked(self.request.id):
        logger.info(
            f"[Task {self.request.id}] Task revoked before start; skipping document {document_id}"
        )
        return {"document_id": document_id, "status": "cancelled", "task_id": self.request.id}

    try:
        result = run_async(_process_document_async(document_id, tenant_id, self.request.id))
        logger.info(f"[Task {self.request.id}] Completed processing for document {document_id}")

        # Trigger community update only when no docs are still in flight.
        # Triggering per-doc with full Leiden causes all community summaries to be wiped
        # and re-summarized on every completion — LLM quota waste.
        # Instead: if communities already exist, run incremental (skip_detection=True):
        #   - assign new orphan entities to nearest community
        #   - mark only affected communities stale
        #   - summarizer re-summarizes only those
        # Full Leiden only runs when no communities exist (first ingestion).
        try:
            pending = run_async(_count_pending_docs_async(tenant_id))
            if pending > 0:
                logger.info(
                    f"[Task {self.request.id}] {pending} doc(s) still in flight for tenant "
                    f"{tenant_id}, deferring community update"
                )
            else:
                has_communities = run_async(_communities_exist_async(tenant_id))
                if has_communities:
                    logger.info(
                        f"[Task {self.request.id}] Communities exist — incremental update "
                        f"(skip Leiden) for tenant {tenant_id}"
                    )
                    process_communities.delay(tenant_id, skip_detection=True)
                else:
                    logger.info(
                        f"[Task {self.request.id}] No communities — full Leiden detection "
                        f"for tenant {tenant_id}"
                    )
                    process_communities.delay(tenant_id)
        except Exception as e:
            logger.warning(f"Failed to trigger community update: {e}")

        return result

    except Exception as e:
        import traceback

        logger.error(
            f"[Task {self.request.id}] Failed processing document {document_id}: {e}\n{traceback.format_exc()}"
        )

        # Update document status to FAILED
        try:
            run_async(_mark_document_failed(document_id, str(e), tenant_id))
        except Exception as fail_err:
            logger.error(f"Failed to mark document as failed: {fail_err}")

        # Retry if not exceeded
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error(
                f"[Task {self.request.id}] Max retries exceeded for document {document_id}"
            )
            # Even on permanent failure, trigger community detection if this was the last doc.
            try:
                pending = run_async(_count_pending_docs_async(tenant_id))
                if pending == 0:
                    process_communities.delay(tenant_id)
            except Exception:
                pass
            raise


@celery_app.task(
    bind=True,
    name="src.workers.tasks.process_communities",
    base=BaseTask,
    max_retries=2,
    queue="low_priority",
)
def process_communities(
    self,
    tenant_id: str,
    skip_detection: bool = False,
    force_full_embedding_resync: bool = False,
    embedding_resync_run_id: str | None = None,
    resume_from: str = "detection",
) -> dict:
    """
    Periodic or triggered task to update graph communities and summaries.

    Args:
        tenant_id: Tenant ID to process communities for.
        skip_detection: If True, skip community detection (Leiden) and only
                        run summarization + embedding on existing communities.
                        Useful for retrying after embedding failures without
                        wiping already-summarized communities.
        force_full_embedding_resync: Re-embed every ready community even when
                        its current content marker is already stored. Intended
                        for explicit repair and migration operations.
        embedding_resync_run_id: Stable ID for a forced resync. Retries retain
                        this value so acknowledged batches are not re-embedded.
        resume_from: First incomplete phase of this task run. Celery retries persist it
            in their kwargs so completed detection/summarization work is not repeated.
    """
    if resume_from not in _COMMUNITY_RESUME_PHASES:
        raise ValueError(f"Unknown community resume phase: {resume_from}")

    if _is_revoked(self.request.id):
        logger.info(
            f"[Task {self.request.id}] Task revoked before start; "
            f"skipping community processing for tenant {tenant_id}"
        )
        return {"status": "cancelled", "tenant_id": tenant_id}

    # Coalesce community runs: multiple documents can trigger this task; only run one per tenant at a time.
    lock_key = f"locks:process_communities:{tenant_id}"
    lock_ttl_seconds = 60 * 60 * 2  # 2h safety TTL in case of worker crash

    redis_client = None
    lock_acquired = False
    try:
        import redis

        from src.api.config import settings

        redis_client = redis.Redis.from_url(settings.db.redis_url)
        lock_acquired = bool(
            redis_client.set(lock_key, str(self.request.id), nx=True, ex=lock_ttl_seconds)
        )
    except Exception as e:
        # If Redis is unavailable, proceed without the lock rather than blocking ingestion.
        logger.warning(f"[Task {self.request.id}] Could not acquire communities lock: {e}")
        lock_acquired = True

    if not lock_acquired:
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(
            f"[Task {self.request.id}] Communities already running for tenant {tenant_id}; skipping"
        )
        return {"status": "skipped", "reason": "already_running", "tenant_id": tenant_id}

    logger.info(f"[Task {self.request.id}] Updating communities for tenant {tenant_id}")

    resync_run_id = embedding_resync_run_id or (
        self.request.id if force_full_embedding_resync else None
    )
    deep_reset_singletons()  # Ensure fresh async clients after fork
    try:
        result = run_async(
            _process_communities_async(
                tenant_id,
                skip_detection=skip_detection,
                force_full_embedding_resync=force_full_embedding_resync,
                force_full_resync_id=resync_run_id,
                task_id=self.request.id,
                resume_from=resume_from,
            )
        )
        return result
    except Exception as e:
        logger.error(f"Community processing failed: {e}")
        retry_kwargs = {
            "skip_detection": skip_detection,
            "force_full_embedding_resync": force_full_embedding_resync,
            "resume_from": getattr(e, "resume_from", resume_from),
        }
        if resync_run_id:
            retry_kwargs["embedding_resync_run_id"] = resync_run_id
        raise self.retry(exc=e, kwargs=retry_kwargs) from e
    finally:
        if redis_client is not None:
            try:
                # Only release if we still own the lock (avoid deleting a newer lock).
                current = redis_client.get(lock_key)
                if current is not None and current.decode() == str(self.request.id):
                    redis_client.delete(lock_key)
            except Exception:
                pass
            try:
                redis_client.close()
            except Exception:
                pass


async def _process_communities_async(
    tenant_id: str,
    skip_detection: bool = False,
    force_full_embedding_resync: bool = False,
    force_full_resync_id: str | None = None,
    task_id: str = "",
    resume_from: str = "detection",
) -> dict:
    """Async implementation of community processing."""
    from src.amber_platform.composition_root import build_vector_store_factory, platform
    from src.api.config import settings
    from src.shared.kernel.runtime import configure_settings

    deep_reset_singletons()
    configure_settings(settings)

    from src.core.database.session import configure_database

    configure_database(settings.db.database_url)

    from src.core.admin_ops.application.tuning_service import TuningService
    from src.core.database.session import get_session_maker
    from src.core.generation.infrastructure.providers.factory import ProviderFactory
    from src.core.graph.application.communities.embeddings import CommunityEmbeddingService
    from src.core.graph.application.communities.leiden import CommunityDetector
    from src.core.graph.application.communities.summarizer import CommunitySummarizer
    from src.core.retrieval.application.embeddings_service import EmbeddingService
    from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL

    next_phase = resume_from
    try:
        # 1. Detection or the pre-existing incremental update.
        detect_res = {"status": "skipped_by_checkpoint", "community_count": 0}
        if resume_from == "detection":
            if not skip_detection:
                # Cooperative cancellation: check BEFORE the destructive _cleanup_old_communities
                # wipe that detect_communities() performs at the start of every full-Leiden run.
                # If the task was revoked after we started running but before the destructive
                # step, abort here so acks_late re-delivery can't silently re-wipe communities.
                if task_id and _is_revoked(task_id):
                    logger.info(
                        f"[Task {task_id}] Revoked before community detection/wipe; "
                        f"aborting for tenant {tenant_id}"
                    )
                    return {"status": "cancelled", "tenant_id": tenant_id}

                detector = CommunityDetector(platform.neo4j_client)
                detect_res = await detector.detect_communities(
                    tenant_id,
                    resolution=settings.leiden_resolution,
                    max_levels=settings.leiden_max_levels,
                    seed=settings.leiden_seed,
                )

                if detect_res["status"] == "skipped":
                    return detect_res
            else:
                detector = CommunityDetector(platform.neo4j_client)
                incremental_res = await detector.assign_orphans_and_mark_stale(tenant_id)
                logger.info(
                    f"Incremental community update for tenant {tenant_id}: "
                    f"assigned={incremental_res.get('assigned', 0)} "
                    f"unassigned={incremental_res.get('unassigned', 0)}"
                )
                detect_res = {"status": "incremental", **incremental_res}
        else:
            logger.info(
                "Resuming community task for tenant %s from %s; skipping detection",
                tenant_id,
                resume_from,
            )
        if resume_from != "embedding":
            next_phase = "summarization"

        tuning_service = TuningService(get_session_maker(), redis_url=settings.db.redis_url)
        tenant_config = await tuning_service.get_effective_tenant_config(tenant_id)

        # Resolve Ollama URL from Tenant Config -> Settings
        res_ollama_url = tenant_config.get("ollama_base_url") or settings.ollama_base_url

        # 2. Summarization
        factory = ProviderFactory(
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=settings.anthropic_api_key,
            ollama_base_url=res_ollama_url,
            default_llm_provider=settings.default_llm_provider,
            default_llm_model=settings.default_llm_model,
            llm_fallback_local=settings.llm_fallback_local,
            llm_fallback_economy=settings.llm_fallback_economy,
            llm_fallback_standard=settings.llm_fallback_standard,
            llm_fallback_premium=settings.llm_fallback_premium,
            openrouter_api_key=settings.openrouter_api_key,
            openrouter_base_url=settings.openrouter_base_url,
            nvidia_nim_api_key=settings.nvidia_nim_api_key,
            nvidia_nim_base_url=settings.nvidia_nim_base_url,
            llm_fallback_enabled=settings.llm_fallback_enabled,
            ollama_cloud_base_url=settings.ollama_cloud_base_url,
            ollama_cloud_api_keys=settings.ollama_cloud_api_keys,
        )

        if resume_from in {"detection", "summarization"}:
            summarizer = CommunitySummarizer(platform.neo4j_client, factory)
            concurrency = (
                tenant_config.get("community_summarization_concurrency")
                or settings.community_summarization_concurrency
            )
            await summarizer.summarize_all_stale(
                tenant_id,
                tenant_config=tenant_config,
                concurrency=int(concurrency),
            )
        else:
            logger.info("Resuming community task for tenant %s from embedding", tenant_id)

        next_phase = "embedding"

        # 3. Embeddings
        # Resolve embedding provider/model from tenant_config first (mirrors
        # RetrievalService._resolve_embedding_service), falling back to system defaults.
        # This ensures community embedding WRITES use the same vector space as GLOBAL
        # search QUERIES, which also honour the tenant override.
        t_embedding_provider = (
            tenant_config.get("embedding_provider") or settings.default_embedding_provider
        )
        t_embedding_model = tenant_config.get("embedding_model") or settings.default_embedding_model

        # Use the already-configured ProviderFactory (which carries the tenant's ollama URL)
        # to get the correct embedding provider.
        embedding_provider = factory.get_embedding_provider(
            provider_name=t_embedding_provider,
            model=t_embedding_model,
        )
        embedding_model = (
            t_embedding_model
            or DEFAULT_EMBEDDING_MODEL.get(t_embedding_provider or "ollama")
            or getattr(embedding_provider, "default_model", None)
            or embedding_provider.get_default_model()
        )
        embedding_svc = EmbeddingService(
            provider=embedding_provider,
            model=embedding_model,
            dimensions=settings.embedding_dimensions or 1536,
        )
        vector_store_factory = build_vector_store_factory()
        embedding_dimensions = settings.embedding_dimensions or 1536
        comm_vector_store = vector_store_factory(
            embedding_dimensions,
            collection_name="community_embeddings",
        )

        # Initialize Sparse Service
        sparse_svc = None
        try:
            from src.amber_platform.composition_root import platform

            sparse_svc = platform.sparse_embedding_service
        except Exception as e:
            logger.warning(f"Failed to initialize SparseEmbeddingService: {e}")

        comm_embedding_svc = CommunityEmbeddingService(
            embedding_service=embedding_svc,
            vector_store=comm_vector_store,
            sparse_embedding_service=sparse_svc,
        )

        # Fetch ready nodes with their last acknowledged embedding marker. The marker is
        # compared locally because Neo4j does not provide a portable SHA-256 function.
        query = """
        MATCH (c:Community {tenant_id: $tenant_id, status: 'ready'})
        RETURN c.id as id, c.tenant_id as tenant_id, c.level as level, c.title as title,
               c.summary as summary, c.embedding_content_hash as embedding_content_hash,
               c.embedding_resync_run_id as embedding_resync_run_id
        """
        ready_comms = await platform.neo4j_client.execute_read(query, {"tenant_id": tenant_id})
        embedding_provider_name = str(
            getattr(embedding_provider, "provider_name", None) or t_embedding_provider or "unknown"
        )
        sync_stats = await comm_embedding_svc.sync_stale_communities(
            ready_comms,
            graph_client=platform.neo4j_client,
            provider=embedding_provider_name,
            model=embedding_model,
            dimensions=embedding_dimensions,
            force_full_resync=force_full_embedding_resync,
            force_full_resync_id=force_full_resync_id,
            should_cancel=lambda: bool(task_id and _is_revoked(task_id)),
        )
        logger.info(
            "Community embedding pass for tenant %s: ready=%s candidates=%s "
            "skipped_current=%s embedded=%s batches=%s force_full_resync=%s",
            tenant_id,
            sync_stats.ready,
            sync_stats.candidates,
            sync_stats.skipped_current,
            sync_stats.embedded,
            sync_stats.batches,
            force_full_embedding_resync,
        )

        if sync_stats.cancelled:
            return {
                "status": "cancelled",
                "tenant_id": tenant_id,
                "communities_detected": detect_res.get("community_count", 0),
                "communities_embedded": sync_stats.embedded,
                "communities_skipped_current": sync_stats.skipped_current,
            }

        return {
            "status": "success",
            "communities_detected": detect_res.get("community_count", 0),
            "communities_ready": sync_stats.ready,
            "communities_embedding_candidates": sync_stats.candidates,
            "communities_skipped_current": sync_stats.skipped_current,
            "communities_embedded": sync_stats.embedded,
            "community_embedding_batches": sync_stats.batches,
            "force_full_embedding_resync": force_full_embedding_resync,
            "embedding_resync_run_id": force_full_resync_id,
        }
    except Exception as e:
        raise CommunityPhaseError(next_phase, e) from e
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
    from src.amber_platform.composition_root import platform
    from src.core.database.session import reset_engine
    from src.core.generation.infrastructure.providers import factory

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

    # 4. Ollama/OpenAI httpx clients (prevent "attached to different loop" errors)
    try:
        from src.core.generation.infrastructure.providers.ollama import (
            reset_client as reset_ollama_client,
        )

        reset_ollama_client()
    except Exception:
        pass  # Ollama module may not be available in all envs

    # 4b. OpenAI client cache (supports multiple providers: OpenAI, OpenRouter, NIM)
    try:
        from src.core.generation.infrastructure.providers import openai as openai_mod

        openai_mod._openai_clients.clear()
    except Exception:
        pass

    # 5. Document Summarizer (Reset singleton instance)
    try:
        from src.core.generation.application.intelligence.document_summarizer import (
            reset_document_summarizer,
        )

        reset_document_summarizer()
    except ImportError:
        pass

    # 6. Metrics Collector (Clear LRU cache)
    try:
        from src.amber_platform.composition_root import build_metrics_collector

        build_metrics_collector.cache_clear()
    except ImportError:
        pass

    # 7. Platform Registry (Force reset to ensure fresh connections)
    platform._milvus_vector_store = None

    logger.info("Platform registry singletons reset.")


async def _process_document_async(document_id: str, tenant_id: str, task_id: str) -> dict:
    """
    Async implementation of document processing.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.amber_platform.composition_root import build_vector_store_factory, platform
    from src.api.config import settings

    # Context isolation: Reset EVERYTHING that might be stale or bound to a closed loop
    deep_reset_singletons()

    from src.amber_platform.composition_root import configure_settings

    configure_settings(settings)

    from src.core.database.session import configure_database

    configure_database(settings.db.database_url)

    from src.shared.kernel.runtime import configure_settings as configure_runtime_settings

    configure_runtime_settings(settings)

    # Move DB initialization earlier to fetch tenant config
    # ERROR FIX: Ensure domain models are imported before session usage to avoid Mapper errors

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Fetch Tenant Config for correct Provider Init
    from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import (
        PostgresTenantRepository,
    )

    resolved_ollama_url = settings.ollama_base_url
    tenant_runtime_config: dict = {}
    try:
        async with async_session() as tmp_session:
            from sqlalchemy import text as _text

            await tmp_session.execute(
                _text("SELECT set_config('app.current_tenant', :tid, false)"), {"tid": tenant_id}
            )
            await tmp_session.execute(
                _text("SELECT set_config('app.is_super_admin', 'true', false)")
            )
            t_repo = PostgresTenantRepository(tmp_session)
            t_obj = await t_repo.get(tenant_id)
            if t_obj and t_obj.config:
                tenant_runtime_config = t_obj.config
                resolved_ollama_url = t_obj.config.get("ollama_base_url") or resolved_ollama_url
    except Exception as e:
        logger.warning(f"Failed to fetch tenant config for provider init: {e}")

    from src.core.generation.infrastructure.providers.factory import init_providers

    init_providers(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
        ollama_base_url=resolved_ollama_url,
        llm_fallback_local=settings.llm_fallback_local,
        llm_fallback_economy=settings.llm_fallback_economy,
        llm_fallback_standard=settings.llm_fallback_standard,
        llm_fallback_premium=settings.llm_fallback_premium,
        embedding_fallback_order=settings.embedding_fallback_order,
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_base_url=settings.openrouter_base_url,
        nvidia_nim_api_key=settings.nvidia_nim_api_key,
        nvidia_nim_base_url=settings.nvidia_nim_base_url,
        llm_fallback_enabled=settings.llm_fallback_enabled,
        ollama_cloud_base_url=settings.ollama_cloud_base_url,
        ollama_cloud_api_keys=settings.ollama_cloud_api_keys,
    )

    from src.core.graph.application.sync_config import resolve_graph_sync_runtime_config
    from src.core.graph.domain.ports.graph_client import set_graph_client
    from src.core.graph.domain.ports.graph_extractor import set_graph_extractor
    from src.core.ingestion.infrastructure.extraction.graph_extractor import GraphExtractor

    graph_sync_config = resolve_graph_sync_runtime_config(
        settings=settings,
        tenant_config=tenant_runtime_config,
    )
    set_graph_extractor(
        GraphExtractor(
            use_gleaning=graph_sync_config.use_gleaning,
            max_gleaning_steps=graph_sync_config.max_gleaning_steps,
        )
    )
    set_graph_client(platform.neo4j_client)

    try:
        async with async_session() as session:
            from src.core.database.session import configure_worker_session

            await configure_worker_session(session, tenant_id)
            # Initialize services
            from src.core.events.dispatcher import EventDispatcher
            from src.core.ingestion.application.ingestion_service import IngestionService
            from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
                PostgresDocumentRepository,
            )
            from src.core.ingestion.infrastructure.uow.postgres_uow import PostgresUnitOfWork
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
                vector_store=None,  # vector_store_factory used internally or passed if needed?
                # In previous code vector_store was None but vector_store_factory passed.
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
                "task_id": task_id,
            }
    finally:
        # Close Neo4j connection before disposing engine
        # This prevents "attached to a different loop" errors
        try:
            await platform.neo4j_client.close()
        except Exception as e:
            logger.warning(f"Failed to close Neo4j client: {e}")

        await engine.dispose()


async def _count_pending_docs_async(tenant_id: str) -> int:
    """Return count of docs for tenant still in a non-terminal processing state."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.api.config import settings

    engine = create_async_engine(settings.db.database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(*) FROM documents "
                    "WHERE tenant_id = :tid "
                    "AND status IN ('INGESTED','EXTRACTING','CLASSIFYING','CHUNKING','EMBEDDING','GRAPH_SYNC')"
                ),
                {"tid": tenant_id},
            )
            return result.scalar_one()
    finally:
        await engine.dispose()


async def _communities_exist_async(tenant_id: str) -> bool:
    """Return True if at least one Community node exists for this tenant in Neo4j."""
    import os

    from neo4j import AsyncGraphDatabase

    from src.api.config import settings

    uri = settings.db.neo4j_uri or os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = settings.db.neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    password = settings.db.neo4j_password or os.environ.get("NEO4J_PASSWORD", "neo4j")

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        async with driver.session() as session:
            result = await session.run(
                "MATCH (c:Community {tenant_id: $tid}) RETURN count(c) > 0 AS exists LIMIT 1",
                {"tid": tenant_id},
            )
            record = await result.single()
            return bool(record["exists"]) if record else False
    finally:
        await driver.close()


async def _mark_document_failed(document_id: str, error: str, tenant_id: str = ""):
    """Mark document as failed in DB."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session

            await configure_worker_session(session, tenant_id)
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
            message = {"document_id": document_id, "status": status, "progress": progress}
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
        message = {"benchmark_id": benchmark_id, "status": status, "progress": progress}
        if error:
            message["error"] = error

        r.publish(channel, json.dumps(message))
        r.close()
    except Exception as e:
        logger.warning(f"Failed to publish benchmark status: {e}")


@celery_app.task(
    bind=True, name="src.workers.tasks.run_ragas_benchmark", base=BaseTask, max_retries=1
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
            run_async(_mark_benchmark_failed(benchmark_run_id, str(e), tenant_id))
        except Exception as fail_err:
            logger.error(f"Failed to mark benchmark as failed: {fail_err}")

        raise


async def _run_ragas_benchmark_async(benchmark_run_id: str, tenant_id: str, task_id: str) -> dict:
    """Async implementation of Ragas benchmark execution."""
    import json
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings

    # Defer heavy imports to after status update
    # from src.core.admin_ops.application.evaluation.ragas_service import RagasService
    from src.core.admin_ops.domain.benchmark_run import BenchmarkRun, BenchmarkStatus

    # Create async session
    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session

            await configure_worker_session(session, tenant_id)
            # Fetch benchmark run
            result = await session.execute(
                select(BenchmarkRun).where(BenchmarkRun.id == benchmark_run_id)
            )
            benchmark = result.scalars().first()

            if not benchmark:
                raise ValueError(f"BenchmarkRun {benchmark_run_id} not found")

            # Update status to RUNNING
            benchmark.status = BenchmarkStatus.RUNNING
            benchmark.started_at = datetime.now(UTC)
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
                f"tests/data/{benchmark.dataset_name}",
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
                raise FileNotFoundError(
                    f"Dataset {benchmark.dataset_name} not found in any search path"
                )

            # Update progress: Dataset loaded
            benchmark.metrics = {"progress": 10}
            await session.commit()
            _publish_benchmark_status(benchmark_run_id, "running", 10)

            # Initialize RAG Services
            from openai import AsyncOpenAI

            from src.core.admin_ops.application.evaluation.ragas_service import RagasService
            from src.core.generation.application.generation_service import GenerationService
            from src.core.retrieval.application.retrieval_service import (
                RetrievalConfig,
                RetrievalService,
            )

            # Initialize Ragas
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            ragas_service = RagasService(llm_client=client)

            # Fetch Tenant Config for RAG Services
            from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import (
                PostgresTenantRepository,
            )

            resolved_ollama_url = settings.ollama_base_url
            try:
                # We need a separate session or query execution to get tenant config
                # Since we are already in an async session, we can reuse it
                t_repo = PostgresTenantRepository(session)
                t_obj = await t_repo.get(tenant_id)
                if t_obj and t_obj.config:
                    resolved_ollama_url = t_obj.config.get("ollama_base_url") or resolved_ollama_url
            except Exception as e:
                logger.warning(f"Failed to fetch tenant config for benchmark: {e}")

            # Initialize RAG Pipeline
            retrieval_config = RetrievalConfig(
                milvus_host=settings.db.milvus_host,
                milvus_port=settings.db.milvus_port,
            )
            retrieval_service = RetrievalService(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key,
                ollama_base_url=resolved_ollama_url,
                redis_url=settings.db.redis_url,
                config=retrieval_config,
            )
            generation_service = GenerationService(
                openai_api_key=settings.openai_api_key,
                anthropic_api_key=settings.anthropic_api_key,
                ollama_base_url=resolved_ollama_url,
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

                # 1. Execute Retrieval (privileged background task: search all tenant documents)
                from src.core.tenants.application.query_scopes import resolve_query_scopes

                worker_scopes = resolve_query_scopes(tenant_id, enforce_groups=False)
                retrieval_result = await retrieval_service.retrieve(
                    query=query, tenant_id=tenant_id, top_k=5, query_scopes=worker_scopes
                )

                # 2. Execute Generation
                if retrieval_result.chunks:
                    gen_result = await generation_service.generate(
                        query=query, candidates=retrieval_result.chunks
                    )
                    generated_answer = gen_result.answer
                    retrieved_contexts = [c.get("content", "") for c in retrieval_result.chunks]
                else:
                    generated_answer = "I couldn't find any relevant information."
                    retrieved_contexts = []

                logger.info(f"Processing Sample {i + 1}/{total_samples} - Query: {query[:30]}...")

                # Evaluate using RagasService
                # Pass GENERATED answer and RETRIEVED contexts (this is the real benchmark)
                eval_result = await ragas_service.evaluate_sample(
                    query=query,
                    context=retrieved_contexts,  # Pass list of strings
                    response=generated_answer,
                )

                import math

                def clean_score(score):
                    if score is None:
                        return None
                    if isinstance(score, float) and (math.isnan(score) or math.isinf(score)):
                        return None
                    return score

                details.append(
                    {
                        "query": query,
                        "faithfulness": clean_score(eval_result.faithfulness),
                        "response_relevancy": clean_score(eval_result.response_relevancy),
                        "context_precision": clean_score(eval_result.context_precision),
                        "context_recall": clean_score(eval_result.context_recall),
                    }
                )

                # Publish progress (Scale 15% to 100%)
                metrics_progress = 15 + int((i + 1) / total_samples * 85)
                _publish_benchmark_status(benchmark_run_id, "running", metrics_progress)

                # Update progress in DB for polling UI
                benchmark.metrics = {"progress": metrics_progress}
                await session.commit()

            # Aggregate metrics
            faith_scores = [d["faithfulness"] for d in details if d["faithfulness"] is not None]
            rel_scores = [
                d["response_relevancy"] for d in details if d["response_relevancy"] is not None
            ]

            metrics = {
                "faithfulness": sum(faith_scores) / len(faith_scores) if faith_scores else 0.0,
                "response_relevancy": sum(rel_scores) / len(rel_scores) if rel_scores else 0.0,
                "samples_evaluated": len(details),
            }

            # Update benchmark with results
            benchmark.status = BenchmarkStatus.COMPLETED
            benchmark.completed_at = datetime.now(UTC)
            benchmark.metrics = metrics
            benchmark.details = details
            await session.commit()

            _publish_benchmark_status(benchmark_run_id, "completed", 100)

            return {
                "benchmark_run_id": benchmark_run_id,
                "status": "completed",
                "metrics": metrics,
                "samples_evaluated": len(details),
                "task_id": task_id,
            }
    finally:
        await engine.dispose()


async def _mark_benchmark_failed(benchmark_run_id: str, error: str, tenant_id: str = ""):
    """Mark benchmark as failed in DB."""
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    from src.core.admin_ops.domain.benchmark_run import BenchmarkRun, BenchmarkStatus

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session

            await configure_worker_session(session, tenant_id)
            result = await session.execute(
                select(BenchmarkRun).where(BenchmarkRun.id == benchmark_run_id)
            )
            benchmark = result.scalars().first()

            if benchmark:
                benchmark.status = BenchmarkStatus.FAILED
                benchmark.completed_at = datetime.now(UTC)
                benchmark.error_message = error
                await session.commit()
                _publish_benchmark_status(benchmark_run_id, "failed", 100, error=error)
    finally:
        await engine.dispose()
