"""
Ingestion Service
=================

Service for handling document ingestion, registration, and file management.
"""

import asyncio
import hashlib
import io
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from src.core.events.dispatcher import EventDispatcher, StateChangeEvent
from src.core.generation.application.intelligence.strategies import STRATEGIES, DocumentDomain
from src.core.generation.application.llm_steps import resolve_llm_step_config
from src.core.graph.application.enrichment import GraphEnricher
from src.core.graph.application.processor import GraphProcessor
from src.core.ingestion.application.chunking.semantic import SemanticChunker
from src.core.ingestion.application.document_taxonomy import classify_document_taxonomy
from src.core.ingestion.domain.document import Document
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
from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.state.machine import DocumentStatus, InvalidTransitionError, TransitionManager
from src.core.tenants.application.active_vector_collection import resolve_active_vector_collection
from src.core.tenants.domain.ports.tenant_repository import TenantRepository
from src.shared.context import set_current_tenant
from src.shared.identifiers import DocumentId

logger = logging.getLogger(__name__)


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

    async def _cleanup_failed_document_artifacts(self, document: Document) -> None:
        """
        Best-effort removal of partial Milvus vectors and Neo4j graph data left
        behind by a document that failed mid-pipeline.

        Called from the `-> FAILED` exception handler in `process_document` so a
        later same-`document_id` retry (`TransitionManager` allows
        `FAILED -> INGESTED`/`FAILED -> EXTRACTING`) never inherits stale
        chunks/entities from the failed attempt. Milvus and Neo4j are cleaned
        independently so a failure in one does not skip the other. This method
        never raises: a cleanup failure must never mask the original ingestion
        error or block persistence of the FAILED status.
        """
        if self.vector_store:
            try:
                deleted = await self.vector_store.delete_by_document(
                    document.id, document.tenant_id
                )
                logger.info(
                    f"FAILED cleanup: removed {deleted} Milvus vector(s) for {document.id}"
                )
            except Exception as vec_err:
                logger.warning(
                    f"FAILED cleanup: Milvus delete failed for {document.id}: {vec_err}"
                )

        if self.neo4j_client:
            try:
                collect_cypher = """
                MATCH (c:Chunk {document_id: $document_id, tenant_id: $tenant_id})-[:MENTIONS]->(e:Entity)
                WHERE NOT EXISTS {
                    MATCH (other:Chunk)-[:MENTIONS]->(e)
                    WHERE other.document_id <> $document_id
                }
                MATCH (e)-[:BELONGS_TO]->(comm:Community)
                RETURN collect(DISTINCT comm.id) AS ids
                """
                rows = await self.neo4j_client.execute_read(
                    collect_cypher,
                    {"document_id": document.id, "tenant_id": document.tenant_id},
                )
                affected_community_ids = rows[0]["ids"] if rows else []

                delete_cypher = """
                MATCH (c:Chunk {document_id: $document_id, tenant_id: $tenant_id})
                OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
                WITH collect(DISTINCT c) AS chunks, collect(DISTINCT e) AS entities
                FOREACH (ch IN chunks | DETACH DELETE ch)
                WITH entities
                UNWIND entities AS entity
                WITH DISTINCT entity
                WHERE entity IS NOT NULL AND NOT (entity)<-[:MENTIONS]-()
                DETACH DELETE entity
                """
                await self.neo4j_client.execute_write(
                    delete_cypher,
                    {"document_id": document.id, "tenant_id": document.tenant_id},
                )

                if affected_community_ids:
                    stale_cypher = """
                    MATCH (comm:Community {tenant_id: $tenant_id})
                    WHERE comm.id IN $ids
                      AND EXISTS { (:Entity)-[:BELONGS_TO]->(comm) }
                    SET comm.is_stale = true
                    """
                    await self.neo4j_client.execute_write(
                        stale_cypher,
                        {"tenant_id": document.tenant_id, "ids": affected_community_ids},
                    )

                logger.info(
                    f"FAILED cleanup: removed Neo4j graph chunks/entities for {document.id}"
                )
            except Exception as graph_err:
                logger.warning(
                    f"FAILED cleanup: Neo4j delete failed for {document.id}: {graph_err}"
                )

    async def register_document(
        self,
        tenant_id: str,
        filename: str,
        file_content: bytes,
        content_type: str = "application/octet-stream",
        metadata_: dict[str, Any] | None = None,
        folder_id: str | None = None,
        source_url: str | None = None,
        source_type: str = "file",
    ) -> Document:
        """
        Register a new document in the system.

        Deduplication is a two-level lookup:
          1. Exact content match (content_hash, tenant-scoped) - always wins,
             returns the existing document unchanged.
          2. Secondary-key match: source_url if provided, else filename
             (tenant-scoped). If a match is found whose content differs, its
             ROW IS REUSED - the id is preserved and the row is updated in
             place ("replace"), rather than creating a new document.
             Preserving the id is mandatory, not an optimization:
             `document_shares.document_id` and `group_document_access.document_id`
             both have `ON DELETE CASCADE` FKs, so a delete+create here would
             silently drop shares/group grants already issued for this document.

        If neither lookup matches, a new document is created (unchanged
        behavior), optionally stamped with source_url/source_type.

        Args:
            tenant_id: Tenant identifier
            filename: Original filename
            file_content: Raw file bytes
            content_type: MIME type
            source_url: Optional canonical source identifier (e.g. a connector
                item id/URL). Takes priority over filename as the secondary
                dedup key when provided.
            source_type: Source category (e.g. "file", or a connector type).
                Only applied when a new document is created.

        Returns:
            Document: The registered document
        """
        # 1. Calculate SHA-256 hash
        content_hash = hashlib.sha256(file_content).hexdigest()

        # 2a. Exact content match - always wins, regardless of filename/source_url.
        existing_doc = await self.document_repository.find_by_content_hash(tenant_id, content_hash)

        if existing_doc:
            logger.info(f"Document deduplicated: {filename} (ID: {existing_doc.id})")
            return existing_doc

        # 2b. Secondary-key match: source_url takes priority over filename.
        if source_url:
            secondary_match = await self.document_repository.find_by_source_url(
                tenant_id, source_url
            )
        else:
            secondary_match = await self.document_repository.find_by_filename(tenant_id, filename)

        # 2c. Replace branch. By construction this match always has a
        # different content_hash: an identical hash would already have
        # returned above via find_by_content_hash.
        if secondary_match and secondary_match.content_hash != content_hash:
            return await self._replace_document_content(
                existing_doc=secondary_match,
                tenant_id=tenant_id,
                filename=filename,
                file_content=file_content,
                content_type=content_type,
                content_hash=content_hash,
                metadata_=metadata_,
            )

        # 2d. No match: create a new document (today's behavior, unchanged),
        # plus stamping source_url/source_type when provided.
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

        # Prepare metadata
        doc_metadata = {"original_filename": filename, "content_type": content_type}
        if metadata_:
            doc_metadata.update(metadata_)

        # Stamp taxonomy from folder name
        if folder_id:
            folder_name = await self.document_repository.get_folder_name(folder_id)
        else:
            folder_name = None
        doc_metadata["taxonomy"] = classify_document_taxonomy(
            folder_name=folder_name,
            document_title=filename,
        )

        # 5. Create DB Record
        new_doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            filename=filename,
            content_hash=content_hash,
            storage_path=storage_path,
            status=DocumentStatus.INGESTED,
            source_type=source_type,
            source_url=source_url,
            metadata_=doc_metadata,
            folder_id=folder_id,
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

    async def _invalidate_result_cache(
        self, tenant_id: str, reason: str, *, loud: bool = False
    ) -> None:
        """Drop the tenant's cached answers.

        Two callers, and the replace one is the load-bearing half.

        On the READY path this is housekeeping: the new chunks are in place, so
        the cache is merely out of date.

        On the replace path it is a correctness fix. A replace repoints the
        Document row at new content and a new filename while the OLD chunk rows
        stay in Postgres until the next reprocess rewrites them, and the
        result-cache hit path does not consult document status at all -
        `_fetch_chunks_by_ids` -> `get_chunks(ids)` is a bare id lookup, so the
        non-READY blocklist that guards live vector/graph search does not apply.
        Chunk ids are deterministic and the document id is preserved by design,
        so pre-replace entries resolve successfully instead of falling into the
        "stale entry, re-search" branch: the old text gets served under the new
        filename. Before the two-level dedup this could not happen, because a
        content change minted a new document id and the cached ids stopped
        resolving.

        Doing it here rather than only after a successful reprocess is what makes
        it hold: the READY invalidation lives inside process_document's try, so a
        failed reprocess (status FAILED) never reached it and the stale entries
        survived to their TTL.

        Best-effort by design - a cache that cannot be reached must not fail an
        ingestion, and the underlying stores stay authoritative. No retry loop
        either: that turns a Redis-availability problem into an
        ingestion-availability one.

        `loud` splits the two callers' failure severity. A miss on the READY path
        is comparatively harmless, because the replace already tried to clear the
        same keys. A miss on the replace path has one concrete known-bad outcome -
        old content served under the new filename, indefinitely, bounded only by
        the TTL - so it must not be indistinguishable from routine warning noise.
        """
        try:
            from src.core.cache.result_cache import ResultCache, ResultCacheConfig
            from src.shared.kernel.runtime import get_settings

            cache = ResultCache(ResultCacheConfig(redis_url=get_settings().db.redis_url))
            await cache.invalidate_tenant(tenant_id)
        except Exception as exc:
            message = f"Failed to invalidate result cache ({reason}) for tenant {tenant_id}: {exc}"
            if loud:
                logger.error(message)
            else:
                logger.warning(message)

    async def _replace_document_content(
        self,
        existing_doc: Document,
        tenant_id: str,
        filename: str,
        file_content: bytes,
        content_type: str,
        content_hash: str,
        metadata_: dict[str, Any] | None,
    ) -> Document:
        """
        Replace an existing document's content in place, preserving its id.

        See register_document's docstring for why preserving the id is
        mandatory (document_shares / group_document_access CASCADE on delete
        of the document row).

        Postgres chunks belonging to the old content are NOT purged here:
        the next full reprocess (`process_document`) replaces
        `document.chunks` wholesale, and the `cascade="all, delete-orphan"`
        relationship already deletes the stale rows - no new code needed.
        The Milvus/Neo4j pre-ingest cleanup in `process_document` is
        document_id-scoped and was already correct; it was simply inert
        before this fix because a content change used to mint a new id.

        The object key carries the content hash so a replace never overwrites
        the version it supersedes - see the comment on storage_path below.
        """
        # The key must differ from the previous version's. The id is preserved
        # by design, so `{tenant}/{id}/{filename}` would be the exact key the
        # old content lives under whenever the filename is unchanged, and
        # StorageClient.upload_file does a plain put_object into a bucket
        # created without versioning: the original bytes would be gone, and the
        # pre-ingest cleanup in process_document then drops the old vectors and
        # graph nodes too, so a failed reprocess would leave nothing to recover
        # from. Worse, provisioning_service copies storage_path by reference
        # across tenants ("shared reference, no S3 copy"), so an in-place
        # overwrite would also mutate the content of another tenant's document
        # row pointing at the same object.
        #
        # Before the two-level dedup this property was free: a content change
        # minted a new doc_id, hence a new key. Keying by content_hash keeps it.
        #
        # ponytail: superseded objects are never collected. Add a retention
        # sweep over `{tenant}/{doc_id}/` if storage growth becomes the problem.
        storage_path = f"{tenant_id}/{existing_doc.id}/{content_hash[:12]}/{filename}"
        file_io = io.BytesIO(file_content)

        try:
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

        previous_status = existing_doc.status

        updated_metadata = dict(existing_doc.metadata_ or {})
        updated_metadata.update({"original_filename": filename, "content_type": content_type})
        if metadata_:
            updated_metadata.update(metadata_)

        existing_doc.content_hash = content_hash
        # filename must follow the new content: it is what get_titles_by_ids()
        # reads to label sources in answers, so leaving the old name here would
        # cite updated content under its previous title. Relevant when the match
        # came from source_url and the source renamed the page.
        existing_doc.filename = filename
        existing_doc.storage_path = storage_path
        existing_doc.status = DocumentStatus.INGESTED
        existing_doc.error_message = None
        existing_doc.metadata_ = updated_metadata

        await self.document_repository.save(existing_doc)

        # The row now points at the new content, so any cached answer built from
        # the old chunks is wrong from this moment - not from whenever the
        # reprocess happens to finish, and regardless of whether it finishes at
        # all. See _invalidate_result_cache.
        await self._invalidate_result_cache(
            tenant_id, f"{existing_doc.id} content replaced", loud=True
        )

        await self.event_dispatcher.emit_state_change(
            StateChangeEvent(
                document_id=existing_doc.id,
                old_status=previous_status,
                new_status=DocumentStatus.INGESTED,
                tenant_id=tenant_id,
                details={"filename": filename, "replaced": True},
            )
        )

        logger.info(
            f"Replaced document content in place: {filename} (ID: {existing_doc.id}, "
            f"previous status: {getattr(previous_status, 'value', previous_status)})"
        )
        return existing_doc

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
        try:
            TransitionManager.validate_transition(document.status, DocumentStatus.EXTRACTING)
        except InvalidTransitionError as e:
            logger.warning(
                f"Invalid status transition for {document_id}: {e}. Skipping."
            )
            return
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

            # Use stored content_type from upload metadata first,
            # then fall back to mimetypes.guess_type() (which returns None for .md files)
            stored_ct = None
            if document.metadata_ and isinstance(document.metadata_, dict):
                stored_ct = document.metadata_.get("content_type")

            mime_type, _ = mimetypes.guess_type(document.filename)
            if stored_ct and stored_ct != "application/octet-stream":
                mime_type = stored_ct
            elif not mime_type:
                mime_type = "application/octet-stream"

            extractor = self.content_extractor or get_content_extractor()
            extraction_result = await extractor.extract(
                file_content=file_content, mime_type=mime_type, filename=document.filename
            )

            # 4b. Quality Gate: check extraction result against configured thresholds.
            # If any threshold is breached and mark_low_quality_as_needs_review is enabled,
            # transition to NEEDS_REVIEW and stop processing.
            from src.core.ingestion.infrastructure.extraction.config import extraction_settings

            content_length = len(extraction_result.content) if extraction_result.content else 0
            page_count = (
                extraction_result.metadata.get("page_count") if extraction_result.metadata else None
            )
            content_density = (
                content_length / page_count if page_count and page_count > 0 else None
            )

            quality_failures = []
            if extraction_result.confidence < extraction_settings.min_ocr_confidence:
                quality_failures.append(
                    f"confidence={extraction_result.confidence:.2f} < "
                    f"min={extraction_settings.min_ocr_confidence}"
                )
            if content_length < extraction_settings.min_content_length:
                quality_failures.append(
                    f"content_length={content_length} < "
                    f"min={extraction_settings.min_content_length}"
                )
            if (
                content_density is not None
                and content_density < extraction_settings.min_content_density
            ):
                quality_failures.append(
                    f"content_density={content_density:.2f} < "
                    f"min={extraction_settings.min_content_density}"
                )

            if quality_failures and extraction_settings.mark_low_quality_as_needs_review:
                reason = "; ".join(quality_failures)
                logger.warning(
                    f"Document {document_id} failed quality gate: {reason}. "
                    f"Setting status to NEEDS_REVIEW."
                )
                TransitionManager.validate_transition(
                    document.status, DocumentStatus.NEEDS_REVIEW
                )
                await self.document_repository.update_status(
                    document.id, DocumentStatus.NEEDS_REVIEW
                )
                await self.unit_of_work.commit()
                document.status = DocumentStatus.NEEDS_REVIEW
                await self.event_dispatcher.emit_state_change(
                    StateChangeEvent(
                        document_id=document.id,
                        old_status=DocumentStatus.EXTRACTING,
                        new_status=DocumentStatus.NEEDS_REVIEW,
                        tenant_id=document.tenant_id,
                        details={"reason": reason, "progress": 15},
                    )
                )
                return

            # 5. Classify Domain (Stage 1.4)
            TransitionManager.validate_transition(document.status, DocumentStatus.CLASSIFYING)
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

            # Merge over existing metadata: reprocessing must not drop fields
            # set out-of-band (taxonomy routing, sync/source info, shares).
            _preserved_metadata = dict(document.metadata_ or {})
            _preserved_metadata.update({
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
            })
            document.metadata_ = _preserved_metadata

            # 7. Chunk Content using SemanticChunker (Stage 1.5)
            TransitionManager.validate_transition(document.status, DocumentStatus.CHUNKING)
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

            # 7.5 Contextual enrichment (Anthropic-style contextual retrieval, opt-in)
            enrichment_enabled = bool(
                tenant_config.get(
                    "contextual_enrichment",
                    os.getenv("CONTEXTUAL_ENRICHMENT_ENABLED", "false").lower() == "true",
                )
            )
            if enrichment_enabled and chunks_to_process:
                from src.core.ingestion.application.chunking.contextual import ContextualEnricher

                try:
                    enricher = ContextualEnricher()
                    await enricher.enrich_chunks(
                        chunks_to_process,
                        extraction_result.content,
                        tenant_config=tenant_config,
                        settings=self.settings,
                    )
                except Exception as e:
                    logger.warning(f"Contextual enrichment skipped (error): {e}")

            document.chunks = chunks_to_process
            await self.document_repository.save(document)

            # 8. Generate Embeddings and Store in Milvus
            TransitionManager.validate_transition(document.status, DocumentStatus.EMBEDDING)
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
                tenant_obj = await self.tenant_repository.get(document.tenant_id)
                t_config = tenant_obj.config if tenant_obj and tenant_obj.config else {}

                sys_prov = settings.default_embedding_provider
                sys_model = settings.default_embedding_model
                sys_dims = settings.embedding_dimensions or 1536

                res_prov = t_config.get("embedding_provider") or sys_prov
                res_model = t_config.get("embedding_model") or sys_model
                res_dims = t_config.get("embedding_dimensions") or sys_dims

                # Resolve Ollama URL from Tenant Config -> Settings
                res_ollama_url = t_config.get("ollama_base_url") or settings.ollama_base_url

                try:
                    factory = build_provider_factory(
                        openai_api_key=settings.openai_api_key,
                        ollama_base_url=res_ollama_url,
                        default_embedding_provider=res_prov,
                        default_embedding_model=res_model,
                    )
                except RuntimeError:
                    factory = get_provider_factory()

                # Reduce batch size for Ollama to prevent runner crashes on large inputs
                max_tokens = 2048 if res_prov == "ollama" else None

                # Enforce supports_dimensions: reject reduced-dim requests on unsupported models.
                # A custom/tenant-specified dimension triggers this check; the system default
                # (sys_dims) may also be an explicit reduced dim, so we check whenever res_dims
                # comes from the tenant config or differs from the model's natural dimension.
                if res_dims and res_model:
                    from src.shared.model_registry import (
                        EMBEDDING_MODELS,
                        embedding_supports_dimensions,
                    )
                    model_info = EMBEDDING_MODELS.get(res_prov or "", {}).get(res_model, {})
                    model_native_dims = model_info.get("dimensions")
                    # Only enforce when asking for a reduced (non-native) dimension.
                    if model_native_dims and res_dims != model_native_dims:
                        if not embedding_supports_dimensions(res_model, provider=res_prov):
                            raise ValueError(
                                f"Embedding model '{res_model}' (provider '{res_prov}') does not "
                                f"support dimension reduction. Cannot use "
                                f"embedding_dimensions={res_dims} (model native dim: "
                                f"{model_native_dims}). Remove embedding_dimensions from the "
                                "tenant/system config or switch to a model that supports "
                                "Matryoshka dimension reduction (e.g. text-embedding-3-small)."
                            )

                embedding_service = EmbeddingService(
                    provider=factory.get_embedding_provider(
                        provider_name=res_prov,
                        model=res_model,
                    ),
                    model=res_model,
                    dimensions=res_dims,
                    max_tokens_per_batch=max_tokens,
                )

                from src.core.retrieval.application.sparse_embeddings_service import (
                    SparseEmbeddingService,
                )
                sparse_service = SparseEmbeddingService()

                active_collection = resolve_active_vector_collection(document.tenant_id, t_config)

                if self.vector_store_factory:
                    vector_store = self.vector_store_factory(
                        res_dims, collection_name=active_collection
                    )
                else:
                    logger.debug("Using provided vector store")
                    vector_store = self.vector_store

                # Re-process cleanup: delete stale Milvus vectors and Neo4j chunk nodes
                # from any previous ingestion run before writing new ones.  On first-time
                # ingestion this is a no-op (nothing to delete).
                if vector_store is not None:
                    try:
                        deleted_count = await vector_store.delete_by_document(
                            document.id, document.tenant_id
                        )
                        logger.info(
                            f"Pre-ingest cleanup: removed {deleted_count} stale Milvus vectors "
                            f"for document {document.id} (tenant {document.tenant_id})"
                        )
                    except Exception as _vs_del_err:
                        logger.warning(
                            f"Failed to delete stale Milvus vectors for {document.id}: "
                            f"{_vs_del_err} (continuing)"
                        )

                try:
                    await self.neo4j_client.execute_write(
                        """
                        MATCH (c:Chunk {document_id: $document_id, tenant_id: $tenant_id})
                        DETACH DELETE c
                        """,
                        {"document_id": document.id, "tenant_id": document.tenant_id},
                    )
                    logger.info(
                        f"Pre-ingest cleanup: removed stale Neo4j chunk nodes "
                        f"for document {document.id} (tenant {document.tenant_id})"
                    )
                except Exception as _neo_del_err:
                    logger.warning(
                        f"Failed to delete stale Neo4j chunk nodes for {document.id}: "
                        f"{_neo_del_err} (continuing)"
                    )

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
                logger.debug('Calling embed_texts chunks=%d model=%s', len(chunk_contents), res_model)

                # Callback for granular progress (60->70%)
                async def _on_embedding_progress(completed: int, total: int):
                    if total == 0:
                        return
                    # Scale 60 -> 70
                    progress = 60 + int((completed / total) * 10)
                    await self.event_dispatcher.emit_state_change(
                        StateChangeEvent(
                            document_id=document.id,
                            old_status=DocumentStatus.EMBEDDING,
                            new_status=DocumentStatus.EMBEDDING,
                            tenant_id=document.tenant_id,
                            details={"progress": progress, "chunks_completed": completed, "total_chunks": total},
                        )
                    )

                embeddings, stats = await embedding_service.embed_texts(
                    chunk_contents,
                    metadata={"document_id": document.id},
                    progress_callback=_on_embedding_progress
                )
                logger.debug("embed_texts returned")

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

                # Report Granular Embedding Progress (60-70%)
                # We do this AFTER upserting to keep it simple, or during if the service supported it.
                # Actually, the service now supports it via callback if we update it.
                # But since we batch upsert here at the end, the "embedding generation" is the long part.
                # If we passed a callback to embed_texts, we could get 60->70 updates.


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
            TransitionManager.validate_transition(document.status, DocumentStatus.GRAPH_SYNC)
            await self.document_repository.update_status(document.id, DocumentStatus.GRAPH_SYNC)
            await self.unit_of_work.commit()
            document.status = DocumentStatus.GRAPH_SYNC
            await self.event_dispatcher.emit_state_change(
                StateChangeEvent(
                    document_id=document.id,
                    old_status=DocumentStatus.EMBEDDING,
                    new_status=DocumentStatus.GRAPH_SYNC,
                    tenant_id=document.tenant_id,
                    details={"progress": 70},
                )
            )

            try:
                from src.core.generation.domain.ports.provider_factory import get_provider_factory

                # Define callback for granular progress (70-95%)
                async def _on_graph_progress(completed: int, total: int):
                    if total == 0:
                        return
                    # Scale 70 -> 95 based on chunk completion
                    progress = 70 + int((completed / total) * 25)

                    await self.event_dispatcher.emit_state_change(
                        StateChangeEvent(
                            document_id=document.id,
                            old_status=DocumentStatus.GRAPH_SYNC,
                            new_status=DocumentStatus.GRAPH_SYNC,
                            tenant_id=document.tenant_id,
                            details={
                                "progress": progress,
                                "chunks_completed": completed,
                                "total_chunks": total
                            },
                        )
                    )

                get_provider_factory()
                if chunks_to_process:
                    await self.graph_processor.process_chunks(
                        chunks_to_process,
                        document.tenant_id,
                        filename=document.filename,
                        tenant_config=tenant_config,
                        progress_callback=_on_graph_progress,
                    )
            except Exception as e:
                logger.error(f"Graph processing failed for document {document_id}: {e}")
                raise

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

                # Surface enrichment failures instead of silently shipping an empty
                # summary. extract_summary swallows LLM/parse errors and returns an
                # empty result tagged with `enrichment_error`; flag it on the document
                # (visible in metadata/UI + logs) without failing the whole pipeline.
                enrichment_error = enrichment.get("enrichment_error")
                if enrichment_error or not (document.summary or "").strip():
                    logger.warning(
                        f"Document enrichment produced no summary for {document_id} "
                        f"(reason: {enrichment_error or 'empty result'})"
                    )
                    enr_meta = document.metadata_ or {}
                    enr_meta["enrichmentStatus"] = "failed" if enrichment_error else "empty"
                    if enrichment_error:
                        enr_meta["enrichmentError"] = str(enrichment_error)[:300]
                    document.metadata_ = dict(enr_meta)

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
                raise

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
            TransitionManager.validate_transition(document.status, DocumentStatus.READY)
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

            # Invalidate result cache so stale answers are not served after new doc is ready
            await self._invalidate_result_cache(document.tenant_id, f"{document_id} READY")

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

                    # Best-effort cleanup of partial Milvus/Neo4j artifacts left by this
                    # failed run. A same-document_id retry is a valid transition
                    # (TransitionManager: FAILED -> INGESTED/EXTRACTING); without this,
                    # a retry that produces fewer chunks than the failed attempt leaves
                    # stale chunks/entities behind (chunk drift, orphan-entity pollution
                    # in graph traversal and community summaries). Never raises.
                    await self._cleanup_failed_document_artifacts(document)
            except Exception as inner_err:
                logger.error(f"Failed to update error state for {document_id}: {inner_err}")
            raise
