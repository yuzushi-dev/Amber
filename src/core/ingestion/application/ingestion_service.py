"""
Ingestion Service
=================

Service for handling document ingestion, registration, and file management.
"""

import asyncio
import hashlib
import io
import logging
import time
from collections.abc import Callable
from typing import Any

from src.core.events.dispatcher import EventDispatcher, StateChangeEvent
from src.core.generation.application.intelligence.strategies import STRATEGIES, DocumentDomain
from src.core.generation.application.llm_steps import resolve_llm_step_config
from src.core.graph.application.enrichment import GraphEnricher
from src.core.graph.application.processor import GraphProcessor
from src.core.ingestion.application.chunking.semantic import SemanticChunker
from src.core.ingestion.domain.document import Document
from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.state.machine import DocumentStatus
from src.core.tenants.application.active_vector_collection import resolve_active_vector_collection
from src.shared.context import set_current_tenant
from src.shared.identifiers import DocumentId

logger = logging.getLogger(__name__)


from src.core.ingestion.domain.ports.content_extractor import (
    ContentExtractorPort,
    get_content_extractor,
)
from src.core.ingestion.domain.ports.dispatcher import TaskDispatcher
from src.core.ingestion.domain.ports.document_repository import DocumentRepository
from src.core.ingestion.domain.ports.graph_client import GraphPort
from src.core.ingestion.domain.ports.storage import StoragePort
from src.core.ingestion.domain.ports.unit_of_work import UnitOfWork
from src.core.ingestion.domain.ports.vector_store import VectorStorePort
from src.core.tenants.domain.ports.tenant_repository import TenantRepository


class IngestionService:
    """
    Handles document registration and initial processing steps.
    """

    def __init__(
        self,
        document_repository: DocumentRepository,
        tenant_repository: TenantRepository,
        unit_of_work: UnitOfWork,
        storage_client: StoragePort,
        neo4j_client: GraphPort,
        vector_store: VectorStorePort | None,
        content_extractor: ContentExtractorPort | None = None,
        settings: Any = None,  # Settings object for embedding/LLM config
        task_dispatcher: TaskDispatcher
        | None = None,  # Optional for backward compat during migration
        event_dispatcher: EventDispatcher | None = None,
        vector_store_factory: Callable[[int], VectorStorePort] | None = None,
    ):
        self.document_repository = document_repository
        self.tenant_repository = tenant_repository
        self.unit_of_work = unit_of_work
        self.storage = storage_client
        self.neo4j_client = neo4j_client
        self.vector_store = vector_store
        self.content_extractor = content_extractor
        self.vector_store_factory = vector_store_factory
        self.settings = settings
        self.task_dispatcher = task_dispatcher
        self.event_dispatcher = event_dispatcher or EventDispatcher()

        # Initialize components
        self.chunker = SemanticChunker(STRATEGIES[DocumentDomain.GENERAL])
        self.embedding_service = EmbeddingService()

        # GraphProcessor uses global graph_writer internally, but that's handled by tasks.py patch for safety
        self.graph_processor = GraphProcessor()
        self.graph_enricher = GraphEnricher(self.neo4j_client, self.vector_store)

    async def register_document(
        self,
        tenant_id: str,
        filename: str,
        file_content: bytes,
        content_type: str = "application/octet-stream",
    ) -> Document:
        """
        Register a new document in the system.

        Performs deduplication based on content hash.
        If document exists, returns existing record.
        If new, uploads to storage and creates DB record.

        Args:
            tenant_id: Tenant identifier
            filename: Original filename
            file_content: Raw file bytes
            content_type: MIME type

        Returns:
            Document: The registered document
        """
        # 1. Calculate SHA-256 hash
        content_hash = hashlib.sha256(file_content).hexdigest()

        # 2. Check for existing document
        existing_doc = await self.document_repository.find_by_content_hash(tenant_id, content_hash)

        if existing_doc:
            logger.info(f"Document deduplicated: {filename} (ID: {existing_doc.id})")
            return existing_doc

        # 3. Create New Document
        # We include tenant_id in the hash to ensure uniqueness per tenant while remaining deterministic
        hash_input = f"{tenant_id}_{content_hash}"
        doc_hex = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        doc_id = DocumentId(f"doc_{doc_hex}")
        storage_path = f"{tenant_id}/{doc_id}/{filename}"

        # 4. Upload to MinIO
        # We need a file-like object for upload_file
        file_io = io.BytesIO(file_content)

        try:
            # Run in threadpool if strictly blocking, but MinIO client is thread-safe.
            # We are in an async function, calling a sync method.
            # Ideally we should use run_in_executor, but for now direct call or specific async wrapper.
            # The MinIOClient wrapper is synchronous. We should acknowledge this block.
            # For high throughput we would offload this.
            await asyncio.to_thread(
                self.storage.upload_file,
                object_name=storage_path,
                data=file_io,
                length=len(file_content),
                content_type=content_type,
            )
        except Exception as e:
            logger.error(f"Failed to upload file to storage: {e}")
            raise

        # 5. Create DB Record
        new_doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            filename=filename,
            content_hash=content_hash,
            storage_path=storage_path,
            status=DocumentStatus.INGESTED,
            source_type="file",
            metadata_={"original_filename": filename, "content_type": content_type},
        )

        await self.document_repository.save(new_doc)
        # Note: Caller responsible for commit if needed, or we rely on implicit UoW scope?
        # Usage implies session commit happens outside.

        # 6. Emit Event
        await self.event_dispatcher.emit_state_change(
            StateChangeEvent(
                document_id=doc_id,
                old_status=None,
                new_status=DocumentStatus.INGESTED,
                tenant_id=tenant_id,
                details={"filename": filename},
            )
        )

        logger.info(f"Registered new document: {filename} (ID: {doc_id})")
        return new_doc

    async def process_document(self, document_id: str):
        """
        Orchestrate the document ingestion pipeline.
        """
        logger.debug("Starting process_document for %s", document_id)

        start_time = time.time()

        # 1. Fetch Document
        document = await self.document_repository.get(document_id)

        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Set tenant context for this background task
        set_current_tenant(document.tenant_id)

        # 2. Check State & Transition (INGESTED -> EXTRACTING)
        updated = await self.document_repository.update_status(
            document_id, DocumentStatus.EXTRACTING, old_status=DocumentStatus.INGESTED
        )

        if not updated:
            # Re-fetch to see why
            document = await self.document_repository.get(document_id)
            logger.warning(
                f"Skipping processing for {document_id}: "
                f"Status is {document.status} (expected INGESTED)"
            )
            return

        # Commit directly to release lock/visible state
        await self.unit_of_work.commit()

        # Refresh local object to match DB
        document = await self.document_repository.get(document_id)

        tenant_config: dict[str, Any] = {}
        if self.tenant_repository:
            try:
                tenant_obj = await self.tenant_repository.get(document.tenant_id)
                if tenant_obj and tenant_obj.config:
                    tenant_config = tenant_obj.config
            except Exception as e:
                logger.warning(f"Failed to load tenant config for ingestion: {e}")

        try:
            # 3. Get File from Storage
            # MinIO get_file returns bytes (handled inside wrapper)
            file_content = self.storage.get_file(document.storage_path)

            # 4. Extract Content (Fallback Chain)
            import mimetypes

            mime_type, _ = mimetypes.guess_type(document.filename)
            if not mime_type:
                mime_type = "application/octet-stream"

            extractor = self.content_extractor or get_content_extractor()
            extraction_result = await extractor.extract(
                file_content=file_content, mime_type=mime_type, filename=document.filename
            )

            # 5. Classify Domain (Stage 1.4)
            await self.document_repository.update_status(document.id, DocumentStatus.CLASSIFYING)
            await self.unit_of_work.commit()
            document.status = DocumentStatus.CLASSIFYING

            await self.event_dispatcher.emit_state_change(
                StateChangeEvent(
                    document_id=document.id,
                    old_status=DocumentStatus.EXTRACTING,
                    new_status=DocumentStatus.CLASSIFYING,
                    tenant_id=document.tenant_id,
                    details={"progress": 20},
                )
            )

            from src.core.generation.application.intelligence.classifier import DomainClassifier
            from src.core.generation.application.intelligence.strategies import get_strategy

            classifier = DomainClassifier()
            domain = await classifier.classify(extraction_result.content)
            await classifier.close()

            # 6. Select Strategy
            strategy = get_strategy(domain.value)
            logger.info(
                f"Classified document {document_id} as {domain.value}. Strategy: {strategy.name}"
            )

            document.domain = domain.value

            # Metadata: Initial population (Clean Schema)
            # We preserve internal technical fields (content_type, mime_type) for system use
            # but present a cleaner view for the user.

            file_ext = document.filename.split(".")[-1] if "." in document.filename else ""
            fmt = "PDF" if file_ext.lower() == "pdf" else file_ext.upper()

            # Format creation date DD/MM/YYYY
            # Convert to local time (CET) for user friendliness
            local_dt = document.created_at.astimezone()
            created_date = local_dt.strftime("%d/%m/%Y")
            upload_time = local_dt.strftime("%H:%M")

            document.metadata_ = {
                "title": document.filename.rsplit(".", 1)[0],
                "format": fmt,
                "pageCount": extraction_result.metadata.get("page_count")
                if extraction_result.metadata
                else None,
                "creationDate": created_date,
                "uploadTime": upload_time,
                # Technical preservation
                "content_type": mime_type,
                "mime_type": mime_type,
                "file_size": len(file_content),
            }

            # 7. Chunk Content using SemanticChunker (Stage 1.5)
            await self.document_repository.update_status(document.id, DocumentStatus.CHUNKING)
            await self.unit_of_work.commit()
            document.status = DocumentStatus.CHUNKING

            await self.event_dispatcher.emit_state_change(
                StateChangeEvent(
                    document_id=document.id,
                    old_status=DocumentStatus.CLASSIFYING,
                    new_status=DocumentStatus.CHUNKING,
                    tenant_id=document.tenant_id,
                    details={"progress": 40},
                )
            )

            from src.core.ingestion.application.chunking.semantic import SemanticChunker
            from src.core.ingestion.domain.chunk import Chunk, EmbeddingStatus
            from src.shared.identifiers import generate_chunk_id

            chunker = SemanticChunker(strategy)
            chunk_data_list = chunker.chunk(
                extraction_result.content,
                document_title=document.filename,
                metadata=extraction_result.metadata,
            )

            logger.info(f"Document {document_id} split into {len(chunk_data_list)} chunks")

            chunks_to_process = []
            for cd in chunk_data_list:
                chunk = Chunk(
                    id=generate_chunk_id(document.id, cd.index),
                    tenant_id=document.tenant_id,
                    document_id=document.id,
                    index=cd.index,
                    content=cd.content,
                    tokens=cd.token_count,
                    metadata_={
                        "extractor": extraction_result.extractor_used,
                        "confidence": extraction_result.confidence,
                        "extraction_time": extraction_result.extraction_time_ms,
                        "domain": domain.value,
                        "start_char": cd.start_char,
                        "end_char": cd.end_char,
                        **cd.metadata,
                        **extraction_result.metadata,
                    },
                    embedding_status=EmbeddingStatus.PENDING,
                )
                chunks_to_process.append(chunk)

            document.chunks = chunks_to_process
            await self.document_repository.save(document)

            # 8. Generate Embeddings and Store in Milvus
            await self.document_repository.update_status(document.id, DocumentStatus.EMBEDDING)
            await self.unit_of_work.commit()
            document.status = DocumentStatus.EMBEDDING

            await self.event_dispatcher.emit_state_change(
                StateChangeEvent(
                    document_id=document.id,
                    old_status=DocumentStatus.CHUNKING,
                    new_status=DocumentStatus.EMBEDDING,
                    tenant_id=document.tenant_id,
                    details={"progress": 60, "chunk_count": len(chunks_to_process)},
                )
            )

            vector_store = None
            try:
                settings = self.settings
                from src.core.generation.domain.ports.provider_factory import (
                    build_provider_factory,
                    get_provider_factory,
                )
                from src.core.retrieval.application.embeddings_service import EmbeddingService
                from src.core.retrieval.application.sparse_embeddings_service import (
                    SparseEmbeddingService,
                )

                tenant_obj = await self.tenant_repository.get(document.tenant_id)
                t_config = tenant_obj.config if tenant_obj and tenant_obj.config else {}

                sys_prov = settings.default_embedding_provider
                sys_model = settings.default_embedding_model
                sys_dims = settings.embedding_dimensions or 1536

                res_prov = t_config.get("embedding_provider") or sys_prov
                res_model = t_config.get("embedding_model") or sys_model
                res_dims = t_config.get("embedding_dimensions") or sys_dims

                try:
                    factory = build_provider_factory(
                        openai_api_key=settings.openai_api_key,
                        ollama_base_url=settings.ollama_base_url,
                        default_embedding_provider=res_prov,
                        default_embedding_model=res_model,
                    )
                except RuntimeError:
                    factory = get_provider_factory()

                embedding_service = EmbeddingService(
                    provider=factory.get_embedding_provider(
                        provider_name=res_prov,
                        model=res_model,
                    ),
                    model=res_model,
                    dimensions=res_dims,
                )
                sparse_service = SparseEmbeddingService()

                active_collection = resolve_active_vector_collection(document.tenant_id, t_config)
                if self.vector_store_factory:
                    vector_store = self.vector_store_factory(
                        res_dims, collection_name=active_collection
                    )
                else:
                    vector_store = self.vector_store

                logger.info(
                    f"RESOLVED EMBEDDING CONFIG | Document: {document.id} | Tenant: {document.tenant_id}"
                )
                logger.info(
                    f"  - Tenant Config Provider: {t_config.get('embedding_provider')} (sys default: {sys_prov})"
                )
                logger.info(
                    f"  - Tenant Config Model: {t_config.get('embedding_model')} (sys default: {sys_model})"
                )
                logger.info(f"  - Resolved Provider: {res_prov}")
                logger.info(f"  - Resolved Model: {res_model}")
                logger.info(f"  - Resolved Model: {res_model}")
                logger.info(f"  - Factory: {factory.__class__.__name__}")

                # Capture Embedding Metadata
                # Re-assign dict to trigger SQLAlchemy JSONB change tracking
                meta_update = document.metadata_ or {}
                meta_update["embeddingModel"] = f"{res_prov} {res_model}"
                meta_update["vectorStore"] = active_collection
                document.metadata_ = dict(meta_update)

                if vector_store is None:
                    raise RuntimeError("Vector store not configured")

                chunk_contents = [c.content for c in chunks_to_process]
                embeddings, stats = await embedding_service.embed_texts(
                    chunk_contents, metadata={"document_id": document.id}
                )

                # Log Aggregated Ingestion Metrics
                try:
                    from src.core.admin_ops.application.metrics.collector import MetricsCollector
                    from src.shared.identifiers import generate_query_id
                    from src.shared.kernel.runtime import get_settings

                    m_settings = get_settings()
                    m_collector = MetricsCollector(redis_url=m_settings.db.redis_url)
                    m_label = f"Ingestion: {document.filename} ({len(chunks_to_process)} chunks)"

                    async with m_collector.track_query(
                        generate_query_id(), document.tenant_id, m_label
                    ) as qm:
                        qm.operation = "ingestion"
                        qm.tokens_used = stats.total_tokens
                        qm.cost_estimate = stats.total_cost
                        qm.response = f"Generated {len(chunks_to_process)} embeddings. Tokens: {stats.total_tokens}, Cost: ${stats.total_cost:.4f}"
                        qm.success = True
                        qm.conversation_id = document.filename
                except Exception as e:
                    logger.error(f"Failed to log aggregated ingestion metrics: {e}")

                sparse_embeddings = []
                try:
                    sparse_embeddings = sparse_service.embed_batch(chunk_contents)
                except Exception as e:
                    logger.warning(f"Failed to generate sparse embeddings: {e}")
                    # Fallback to empty sparse vectors to satisfy schema
                    sparse_embeddings = [{} for _ in chunks_to_process]

                milvus_data = []
                for chunk, emb, sparse_emb in zip(
                    chunks_to_process, embeddings, sparse_embeddings, strict=False
                ):
                    data = {
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "tenant_id": document.tenant_id,
                        "content": chunk.content[:65530],
                        "embedding": emb,
                    }
                    if sparse_emb is not None:
                        data["sparse_vector"] = sparse_emb
                    if chunk.metadata_:
                        data.update(chunk.metadata_)
                    milvus_data.append(data)

                await vector_store.upsert_chunks(milvus_data)

                for chunk in chunks_to_process:
                    chunk.embedding_status = EmbeddingStatus.COMPLETED

                chunk_params = [
                    {
                        "id": c.id,
                        "document_id": c.document_id,
                        "tenant_id": document.tenant_id,
                        "content": c.content,
                    }
                    for c in chunks_to_process
                ]
                if chunk_params:
                    await self.neo4j_client.execute_write(
                        """
                        UNWIND $batch as row
                        MERGE (c:Chunk {id: row.id})
                        ON CREATE SET
                            c.document_id = row.document_id,
                            c.tenant_id = row.tenant_id,
                            c.content = row.content,
                            c.created_at = timestamp()
                        """,
                        {"batch": chunk_params},
                    )

                try:
                    self.graph_enricher.vector_store = vector_store
                    for data in milvus_data:
                        await self.graph_enricher.create_similarity_edges(
                            chunk_id=data["chunk_id"],
                            embedding=data["embedding"],
                            tenant_id=document.tenant_id,
                        )
                except Exception as e:
                    logger.error(f"Similarity edge generation failed: {e}")

            except Exception as e:
                logger.error(f"Embedding generation/storage failed for document {document_id}: {e}")
                for chunk in chunks_to_process:
                    chunk.embedding_status = EmbeddingStatus.FAILED
                raise

            finally:
                if vector_store is not None:
                    try:
                        await vector_store.disconnect()
                    except Exception as disconnect_error:
                        logger.warning(f"Failed to disconnect Milvus: {disconnect_error}")

            # 9. Build Knowledge Graph
            await self.document_repository.update_status(document.id, DocumentStatus.GRAPH_SYNC)
            await self.unit_of_work.commit()
            document.status = DocumentStatus.GRAPH_SYNC
            await self.event_dispatcher.emit_state_change(
                StateChangeEvent(
                    document_id=document.id,
                    old_status=DocumentStatus.EMBEDDING,
                    new_status=DocumentStatus.GRAPH_SYNC,
                    tenant_id=document.tenant_id,
                    details={"progress": 80},
                )
            )

            try:
                from src.core.generation.domain.ports.provider_factory import get_provider_factory

                get_provider_factory()
                if chunks_to_process:
                    await self.graph_processor.process_chunks(
                        chunks_to_process,
                        document.tenant_id,
                        filename=document.filename,
                        tenant_config=tenant_config,
                    )
            except Exception as e:
                logger.error(f"Graph processing failed for document {document_id}: {e}")

            # 10. Document Enrichment
            try:
                from src.core.generation.application.intelligence.document_summarizer import (
                    get_document_summarizer,
                )

                summarizer = get_document_summarizer()
                chunk_contents = [c.content for c in chunks_to_process[:10]]
                enrichment = await summarizer.extract_summary(
                    chunks=chunk_contents,
                    document_title=document.filename,
                    tenant_config=tenant_config,
                )
                document.summary = enrichment.get("summary", "")
                document.document_type = enrichment.get("document_type", "other")
                document.hashtags = enrichment.get("hashtags", [])
                document.keywords = enrichment.get("keywords", [])
                if domain and domain.value and domain.value not in document.keywords:
                    document.keywords.append(domain.value)

                # Capture LLM Metadata
                try:
                    llm_cfg = resolve_llm_step_config(
                        tenant_config=tenant_config,
                        step_id="ingestion.document_summarization",
                        settings=self.settings
                        or get_settings(),  # fallback if self.settings is None
                    )
                    meta_update = document.metadata_ or {}
                    meta_update["llmModel"] = f"{llm_cfg.provider} {llm_cfg.model}"
                    document.metadata_ = dict(meta_update)
                except Exception as e:
                    logger.warning(f"Failed to resolve LLM config for metadata: {e}")

            except Exception as e:
                logger.error(f"Document enrichment failed for {document_id}: {e}")

            # 11. Update Document Status -> READY
            # 11b. Finalize Metadata (Duration)
            try:
                duration_seconds = time.time() - start_time
                minutes, secs = divmod(int(duration_seconds), 60)
                duration_str = f"{minutes}m {secs}s" if minutes > 0 else f"{secs}s"

                meta_update = document.metadata_ or {}
                meta_update["uploadDuration"] = duration_str
                document.metadata_ = dict(meta_update)
            except Exception as e:
                logger.warning(f"Failed to set upload duration: {e}")

            # 11. Update Document Status -> READY
            await self.document_repository.update_status(document.id, DocumentStatus.READY)
            await self.unit_of_work.commit()
            document.status = DocumentStatus.READY

            await self.event_dispatcher.emit_state_change(
                StateChangeEvent(
                    document_id=document.id,
                    old_status=DocumentStatus.GRAPH_SYNC,
                    new_status=DocumentStatus.READY,
                    tenant_id=document.tenant_id,
                    details={"progress": 100},
                )
            )

            logger.info(f"Processed document {document_id}")

        except Exception as e:
            logger.exception(f"Failed to process document {document_id}")
            try:
                document = await self.document_repository.get(document_id)
                if document:
                    document.status = DocumentStatus.FAILED
                    # Use shared error mapping for structured persistence
                    try:
                        import json

                        from src.shared.error_handling import map_exception_to_error_data

                        error_data = map_exception_to_error_data(e)
                        document.error_message = json.dumps(error_data)
                    except Exception as map_err:
                        logger.error(f"Failed to map error for {document_id}: {map_err}")
                        document.error_message = f"{type(e).__name__}: {str(e)}"

                    await self.document_repository.save(document)
                    await self.unit_of_work.commit()
            except Exception as inner_err:
                logger.error(f"Failed to update error state for {document_id}: {inner_err}")
            raise
