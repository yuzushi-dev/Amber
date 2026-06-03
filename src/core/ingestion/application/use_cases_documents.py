"""
Document Use Cases
==================

Application layer use cases for document operations.
These contain the business logic extracted from route handlers.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import magic  # python-magic for server-side MIME detection
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.events.dispatcher import EventDispatcher
from src.core.ingestion.application.document_taxonomy import classify_document_taxonomy
from src.core.ingestion.domain.ports.dispatcher import TaskDispatcher
from src.core.ingestion.domain.ports.document_repository import DocumentRepository
from src.core.ingestion.domain.ports.graph_client import GraphPort
from src.core.ingestion.domain.ports.storage import StoragePort
from src.core.ingestion.domain.ports.unit_of_work import UnitOfWork
from src.core.ingestion.domain.ports.vector_store import VectorStorePort
from src.core.tenants.domain.ports.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)

# Allowed MIME types for document uploads
ALLOWED_MIMES = {
    "application/pdf",
    "text/plain",
    "text/html",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/json",
    "text/csv",
    "application/octet-stream",  # fallback
}

# -----------------------------------------------------------------------------
# DTOs
# -----------------------------------------------------------------------------


@dataclass
class UploadDocumentRequest:
    """Request DTO for document upload."""

    tenant_id: str
    filename: str
    content: bytes
    content_type: str
    metadata: dict[str, Any] | None = None
    folder_id: str | None = None
    shared_with_tenant_ids: list[str] | None = None
    share_actor: str | None = None


@dataclass
class UploadDocumentResult:
    """Result DTO for document upload."""

    document_id: str
    status: str
    is_duplicate: bool
    message: str


# -----------------------------------------------------------------------------
# Use Case Implementation
# -----------------------------------------------------------------------------


class UploadDocumentUseCase:
    """
    Use case for uploading a document.

    Handles:
    - File size validation
    - Document registration (with deduplication)
    - Async processing dispatch
    """

    def __init__(
        self,
        document_repository: DocumentRepository,
        tenant_repository: TenantRepository,
        unit_of_work: UnitOfWork,
        storage: StoragePort,
        max_size_bytes: int,
        graph_client: GraphPort,
        vector_store: VectorStorePort | None,
        vector_store_factory: Callable[[int], VectorStorePort] | None = None,
        task_dispatcher: TaskDispatcher | None = None,
        event_dispatcher: EventDispatcher | None = None,
        document_sharing_service=None,
    ):
        """
        Initialize the use case.

        Args:
            document_repository: Document persistence port.
            tenant_repository: Tenant repository port.
            unit_of_work: Unit of Work for transaction boundaries.
            storage: Storage adapter for file operations.
            max_size_bytes: Maximum allowed file size.
            graph_client: Graph database client port.
            vector_store: Vector store instance.
            vector_store_factory: Optional vector store factory for dynamic configs.
            task_dispatcher: Dispatcher for background jobs.
        """
        self._document_repository = document_repository
        self._tenant_repository = tenant_repository
        self._unit_of_work = unit_of_work
        self._storage = storage
        self._max_size_bytes = max_size_bytes
        self._graph_client = graph_client
        self._vector_store = vector_store
        self._vector_store_factory = vector_store_factory
        self._task_dispatcher = task_dispatcher
        self._event_dispatcher = event_dispatcher
        self._document_sharing_service = document_sharing_service

    async def execute(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        """
        Execute the document upload use case.

        Args:
            request: Upload request with tenant, filename, content.

        Returns:
            UploadDocumentResult with document_id and status.

        Raises:
            ValueError: If file is empty or too large.
        """
        # Validate file size
        if len(request.content) == 0:
            raise ValueError("Empty file uploaded")

        if len(request.content) > self._max_size_bytes:
            max_mb = self._max_size_bytes // (1024 * 1024)
            raise ValueError(f"File too large. Max size: {max_mb}MB")

        # Server-side MIME validation using magic bytes
        try:
            detected_mime = magic.from_buffer(request.content[:4096], mime=True)
            declared_mime = (request.content_type or "").split(";")[0].strip().lower()

            if detected_mime not in ALLOWED_MIMES:
                logger.warning(
                    "MIME validation failed: detected=%s, declared=%s, filename=%s",
                    detected_mime, declared_mime, request.filename
                )
                raise ValueError(
                    f"Unsupported file type: {detected_mime}. "
                    f"Upload rejected."
                )
        except ImportError:
            logger.warning("python-magic not installed; skipping MIME validation")
        except Exception as e:
            if "Unsupported file type" in str(e):
                raise
            logger.warning("MIME validation error: %s", e)

        normalized_share_targets: list[str] | None = None
        if request.shared_with_tenant_ids is not None:
            if request.tenant_id != "default":
                raise ValueError(
                    "shared_with_tenant_ids is only allowed when uploading into the default tenant"
                )
            if not request.share_actor:
                raise ValueError("Default tenant admin privileges required for shared uploads")
            if self._document_sharing_service is None:
                raise ValueError("Document sharing service unavailable")
            normalized_share_targets = await self._document_sharing_service.validate_target_tenant_ids(
                request.shared_with_tenant_ids
            )

        # Register document
        from src.core.ingestion.application.ingestion_service import IngestionService
        from src.core.state.machine import DocumentStatus

        service = IngestionService(
            document_repository=self._document_repository,
            tenant_repository=self._tenant_repository,
            unit_of_work=self._unit_of_work,
            storage_client=self._storage,
            neo4j_client=self._graph_client,
            vector_store=self._vector_store,
            vector_store_factory=self._vector_store_factory,
            event_dispatcher=self._event_dispatcher,
        )
        document = await service.register_document(
            tenant_id=request.tenant_id,
            filename=request.filename,
            file_content=request.content,
            content_type=request.content_type,
            metadata_=request.metadata,
            folder_id=request.folder_id,
        )

        # Commit transaction before dispatching async processing
        await self._unit_of_work.commit()

        if normalized_share_targets:
            await self._document_sharing_service.add_shares(
                document.id,
                normalized_share_targets,
                actor=request.share_actor,
            )

        # Dispatch async processing if new document
        is_duplicate = document.status != DocumentStatus.INGESTED
        if not is_duplicate:
            if self._task_dispatcher:
                await self._task_dispatcher.dispatch(
                    "src.workers.tasks.process_document", args=[document.id, request.tenant_id]
                )
            else:
                # No dispatcher - this is a test or sync execution scenario
                # Caller must handle processing separately
                logger.warning(
                    "No TaskDispatcher available, document not queued for async processing"
                )

        # Invalidate stats cache so numbers update immediately on frontend
        try:
            from src.core.cache.decorators import delete_cache

            # Invalidate for the uploader's tenant
            await delete_cache(f"admin:stats:database:{request.tenant_id}")
            await delete_cache(f"admin:stats:vectors:{request.tenant_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate stats cache: {e}")

        return UploadDocumentResult(
            document_id=document.id,
            status=document.status.value,
            is_duplicate=is_duplicate,
            message="Document accepted for processing"
            if not is_duplicate
            else "Document deduplicated",
        )


@dataclass
class DeleteDocumentRequest:
    """Request DTO for document deletion."""

    document_id: str
    tenant_id: str
    is_super_admin: bool = False


@dataclass
class DeleteDocumentResult:
    """Result DTO for document deletion."""

    document_id: str
    status: str = "deleted"


class DeleteDocumentUseCase:
    """
    Use case for deleting a document.

    Orchestrates deletion across:
    - Graph Database (Neo4j)
    - Vector Store (Milvus)
    - Object Storage (MinIO)
    - Relational Database (PostgreSQL)
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: StoragePort,
        graph_client: GraphPort,
        vector_store_factory,  # Callable returning VectorStorePort
    ):
        self._session = session
        self._storage = storage
        self._graph_client = graph_client
        self._vector_store_factory = vector_store_factory

    async def execute(self, request: DeleteDocumentRequest) -> DeleteDocumentResult:
        """
        Execute document deletion.

        Attempts to clean up all stores (Neo4j, Milvus, MinIO, Postgres).
        It is resilient to cases where the document is already partially deleted.
        """
        from sqlalchemy import select

        from src.core.ingestion.domain.document import Document

        # 1. Access Control & Metadata
        # Even if the document is gone from Postgres, we need fixed info for cleanup.
        query = select(Document).where(Document.id == request.document_id)
        if not request.is_super_admin:
            query = query.where(Document.tenant_id == request.tenant_id)

        result = await self._session.execute(query)
        document = result.scalars().first()

        # Non-super-admin: document must exist in caller's tenant
        if document is None and not request.is_super_admin:
            raise LookupError(f"Document {request.document_id} not found")

        # We determine storage path and tenant_id
        # If document not in Postgres, we use request info for best-effort cleanup
        tenant_id = document.tenant_id if document else request.tenant_id
        storage_path = document.storage_path if document else f"{tenant_id}/{request.document_id}/"

        # 2. Delete from Neo4j (Hardened Query)
        try:
            # Collect communities of entities that will become orphaned by this deletion.
            # Must run BEFORE deletion so we can still traverse the graph.
            affected_community_ids: list[str] = []
            try:
                collect_cypher = """
                MATCH (d:Document {id: $document_id, tenant_id: $tenant_id})
                MATCH (d)-[:HAS_CHUNK]->(ch:Chunk)-[:MENTIONS]->(e:Entity)
                WHERE NOT EXISTS {
                    MATCH (other:Chunk)-[:MENTIONS]->(e)
                    WHERE NOT (d)-[:HAS_CHUNK]->(other)
                }
                MATCH (e)-[:BELONGS_TO]->(c:Community)
                RETURN collect(DISTINCT c.id) AS ids
                """
                rows = await self._graph_client.execute_read(
                    collect_cypher,
                    {"document_id": request.document_id, "tenant_id": tenant_id},
                )
                affected_community_ids = rows[0]["ids"] if rows else []
            except Exception as e:
                logger.warning(f"Failed to collect affected communities before deletion: {e}")

            # This query ensures we also clean up entities that no longer have ANY mentions
            cypher = """
            MATCH (d:Document {id: $document_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
            OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
            WITH d, c, collect(DISTINCT e) AS entities
            DETACH DELETE d, c
            WITH entities
            UNWIND entities AS entity
            WITH entity
            WHERE entity IS NOT NULL AND NOT (entity)<-[:MENTIONS]-()
            DETACH DELETE entity
            """
            await self._graph_client.execute_write(
                cypher,
                {"document_id": request.document_id, "tenant_id": tenant_id},
            )
            logger.info(f"Cleaned up Neo4j data for document {request.document_id}")

            # Post-deletion cleanup: Remove communities and isolated entities that became orphans
            # This is a best-effort background cleanup to keep the graph healthy
            cleanup_cypher = """
            MATCH (c:Community {tenant_id: $tenant_id})
            WHERE NOT EXISTS { (:Entity)-[:BELONGS_TO|IN_COMMUNITY]->(c) }
            DETACH DELETE c
            """
            await self._graph_client.execute_write(cleanup_cypher, {"tenant_id": tenant_id})

            # Clean isolated entities (no relationships at all or only connected to other entities but not chunks)
            # More aggressive: Delete any Entity that is NOT reachable from a Chunk
            orphan_cypher = """
            MATCH (e:Entity {tenant_id: $tenant_id})
            WHERE NOT (:Chunk)-[:MENTIONS]->(e)
            DETACH DELETE e
            """
            await self._graph_client.execute_write(orphan_cypher, {"tenant_id": tenant_id})

            # Mark partially-emptied communities stale so the summarizer re-processes them.
            # Communities fully emptied are already deleted above; this only touches survivors.
            if affected_community_ids:
                mark_stale_cypher = """
                MATCH (c:Community {tenant_id: $tenant_id})
                WHERE c.id IN $ids
                  AND EXISTS { (:Entity)-[:BELONGS_TO]->(c) }
                SET c.is_stale = true
                RETURN count(c) AS marked
                """
                rows = await self._graph_client.execute_write(
                    mark_stale_cypher,
                    {"tenant_id": tenant_id, "ids": affected_community_ids},
                )
                marked = rows[0]["marked"] if rows else 0
                logger.info(f"Marked {marked} communities stale after deleting {request.document_id}")

        except Exception as e:
            logger.warning(f"Failed to delete graph data for document {request.document_id}: {e}")

        # 3. Delete from Milvus
        try:
            vector_store = self._vector_store_factory(tenant_id)
            try:
                await vector_store.delete_by_document(request.document_id, tenant_id)
                logger.info(f"Cleaned up Milvus data for document {request.document_id}")
            finally:
                if hasattr(vector_store, "disconnect"):
                    await vector_store.disconnect()
        except Exception as e:
            logger.warning(f"Failed to delete vectors for document {request.document_id}: {e}")

        # 4. Delete from MinIO
        try:
            if hasattr(self._storage, "delete_file"):
                # Best effort: if it was a folder or specific file
                # In register_document it is f"{tenant_id}/{doc_id}/{filename}"
                # We might need to delete the whole doc folder
                self._storage.delete_file(storage_path)
                logger.info(f"Cleaned up MinIO file: {storage_path}")
        except Exception as e:
            logger.warning(f"Failed to delete file from storage: {e}")

        # 5. Delete from DB (Last, if exists)
        if document:
            await self._session.delete(document)
            await self._session.commit()
            logger.info(f"Removed Postgres record for document {request.document_id}")
        else:
            logger.info(f"Document {request.document_id} already absent from Postgres")

        # 6. Invalidate Stats Cache
        # Ensure stats update immediately
        try:
            from src.core.cache.decorators import delete_cache

            await delete_cache(f"admin:stats:database:{tenant_id}")
            await delete_cache(f"admin:stats:vectors:{tenant_id}")
            # Cache keys might be just the prefix if used with @cached, but here we manually constructed them in maintenance.py
        except Exception as e:
            logger.warning(f"Failed to invalidate stats cache: {e}")

        # Invalidate result cache so stale answers are not served after document deletion
        try:
            from src.core.cache.result_cache import ResultCache, ResultCacheConfig
            from src.shared.kernel.runtime import get_settings

            _rc_settings = get_settings()
            _rc = ResultCache(ResultCacheConfig(redis_url=_rc_settings.db.redis_url))
            await _rc.invalidate_tenant(tenant_id)
        except Exception as e:
            logger.warning(f"Failed to invalidate result cache on document delete: {e}")

        return DeleteDocumentResult(document_id=request.document_id)


# -----------------------------------------------------------------------------
# Get Document Use Case
# -----------------------------------------------------------------------------


@dataclass
class GetDocumentRequest:
    """Request DTO for getting a document."""

    document_id: str
    tenant_id: str | None
    is_super_admin: bool = False


@dataclass
class DocumentOutput:
    """Output DTO for document details."""

    id: str
    filename: str
    title: str
    status: str
    domain: str | None
    tenant_id: str
    folder_id: str | None
    source_type: str | None
    content_type: str | None
    created_at: Any
    summary: str | None
    document_type: str | None
    keywords: list[str]
    hashtags: list[str]
    metadata: dict[str, Any] | None
    stats: dict[str, int]
    ingestion_cost: float = 0.0
    is_shared: bool = False
    owner_tenant_id: str | None = None
    visible_from_tenant_id: str | None = None
    share_mode: str | None = None


class GetDocumentUseCase:
    """
    Use case for retrieving a document with enrichment data.
    """

    def __init__(
        self,
        session: AsyncSession,
        graph_client: GraphPort,
    ):
        self._session = session
        self._graph_client = graph_client

    async def execute(self, request: GetDocumentRequest) -> DocumentOutput:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from src.core.ingestion.domain.document import Document
        from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
            PostgresDocumentRepository,
        )

        if request.is_super_admin:
            query = (
                select(Document)
                .options(selectinload(Document.folder))
                .where(Document.id == request.document_id)
            )
            result = await self._session.execute(query)
            document = result.scalars().first()
            if not document:
                raise LookupError(f"Document {request.document_id} not found")

            is_shared = False
            owner_tenant_id = document.tenant_id
            visible_from_tenant_id = document.tenant_id
            share_mode = None
        else:
            repository = PostgresDocumentRepository(self._session)
            visible_document = await repository.get_visible(request.document_id, request.tenant_id)
            if not visible_document:
                raise LookupError(f"Document {request.document_id} not found")

            document = visible_document.document
            is_shared = visible_document.is_shared
            owner_tenant_id = visible_document.owner_tenant_id
            visible_from_tenant_id = visible_document.visible_from_tenant_id
            share_mode = visible_document.share_mode

        # 2. Compute Stats & Cost
        stats = await compute_document_stats(self._session, self._graph_client, document.id)
        cost = await compute_document_cost(self._session, document.id)

        # 3. Determine Content Type
        content_type = document.metadata_.get("content_type")
        if not content_type:
            if document.filename:
                import mimetypes

                content_type, _ = mimetypes.guess_type(document.filename)

            if not content_type:
                content_type = "application/octet-stream"

        # 4. Dynamic Metadata (Folder)
        metadata = document.metadata_ or {}
        if document.folder:
            metadata = metadata.copy()
            metadata["folder"] = document.folder.name

        return DocumentOutput(
            id=document.id,
            filename=document.filename,
            title=document.filename,
            status=document.status.value,
            domain=document.domain,
            tenant_id=document.tenant_id,
            folder_id=document.folder_id,
            source_type=document.source_type,
            content_type=content_type,
            created_at=document.created_at,
            summary=document.summary,
            document_type=document.document_type,
            keywords=document.keywords or [],
            hashtags=document.hashtags or [],
            metadata=metadata,
            stats=stats,
            ingestion_cost=cost,
            is_shared=is_shared,
            owner_tenant_id=owner_tenant_id,
            visible_from_tenant_id=visible_from_tenant_id,
            share_mode=share_mode,
        )


@dataclass
class UpdateDocumentRequest:
    """Request DTO for updating a document."""

    document_id: str
    tenant_id: str
    is_super_admin: bool = False
    title: str | None = None
    folder_id: str | None = None


class UpdateDocumentUseCase:
    """
    Use case for updating a document.
    """

    def __init__(
        self,
        session: AsyncSession,
        graph_client: GraphPort,
    ):
        self._session = session
        self._graph_client = graph_client

    async def execute(self, request: UpdateDocumentRequest) -> DocumentOutput:
        from sqlalchemy import select

        from src.core.ingestion.domain.document import Document
        from src.core.ingestion.domain.folder import Folder

        # 1. Fetch Document
        query = select(Document).where(Document.id == request.document_id)
        if not request.is_super_admin:
            query = query.where(Document.tenant_id == request.tenant_id)

        result = await self._session.execute(query)
        document = result.scalars().first()

        if not document:
            raise LookupError(f"Document {request.document_id} not found")

        # 2. Apply Updates
        if request.title is not None:
            document.filename = request.title

        if request.folder_id is not None:
            if request.folder_id == "":
                document.folder_id = None
                # Clear taxonomy when folder is removed
                _meta = dict(document.metadata_ or {})
                _meta["taxonomy"] = classify_document_taxonomy(folder_name=None)
                document.metadata_ = _meta
            else:
                # Verify folder exists
                folder = await self._session.get(Folder, request.folder_id)
                # Check folder ownership if strictly enforced or implied by access
                if not folder or (
                    not request.is_super_admin and folder.tenant_id != request.tenant_id
                ):
                    # If super admin, we expect folder to be valid.
                    # Ideally we should check if folder belongs to same tenant as document anyway.
                    if not folder or folder.tenant_id != document.tenant_id:
                        raise LookupError("Folder not found or invalid")

                document.folder_id = request.folder_id
                # Re-stamp taxonomy when folder changes
                meta = dict(document.metadata_ or {})
                meta["taxonomy"] = classify_document_taxonomy(
                    folder_name=folder.name,
                    document_title=document.filename,
                )
                document.metadata_ = meta

        await self._session.commit()
        await self._session.refresh(document)

        # 3. Compute Stats & Cost & Return
        stats = await compute_document_stats(self._session, self._graph_client, document.id)
        cost = await compute_document_cost(self._session, document.id)

        # Determine content type (duplicated logic, maybe extract to helper if needed often)
        content_type = document.metadata_.get("content_type")
        if not content_type:
            if document.filename:
                import mimetypes

                content_type, _ = mimetypes.guess_type(document.filename)
            if not content_type:
                content_type = "application/octet-stream"

        return DocumentOutput(
            id=document.id,
            filename=document.filename,
            title=document.filename,
            status=document.status.value,
            domain=document.domain,
            tenant_id=document.tenant_id,
            folder_id=document.folder_id,
            source_type=document.source_type,
            content_type=content_type,
            created_at=document.created_at,
            summary=document.summary,
            document_type=document.document_type,
            keywords=document.keywords or [],
            hashtags=document.hashtags or [],
            metadata=document.metadata_,
            stats=stats,
            ingestion_cost=cost,
            is_shared=False,
            owner_tenant_id=document.tenant_id,
            visible_from_tenant_id=document.tenant_id,
            share_mode=None,
        )


async def resolve_graph_document_id(session: AsyncSession, document_id: str) -> str:
    """
    Map a non-default-tenant document ID to the canonical default-tenant ID for Neo4j.
    Documents in non-default tenants share the knowledge graph with the default tenant
    (same filename, different IDs). Returns original document_id if no mapping found.
    """
    from sqlalchemy import select as _select
    from sqlalchemy import text as _text

    from src.core.ingestion.domain.document import Document as _Document

    row = (
        await session.execute(
            _select(_Document.filename, _Document.tenant_id).where(_Document.id == document_id)
        )
    ).first()

    if not row or row.tenant_id == "default":
        return document_id

    # The documents table RLS policy checks only app.current_tenant (not is_super_admin).
    # Temporarily switch to the default tenant context for the cross-tenant lookup.
    original_tenant = row.tenant_id
    try:
        await session.execute(
            _text("SELECT set_config('app.current_tenant', 'default', false)")
        )
        canonical_id = (
            await session.execute(
                _select(_Document.id)
                .where(_Document.filename == row.filename, _Document.tenant_id == "default")
                .limit(1)
            )
        ).scalar()
    finally:
        await session.execute(
            _text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
            {"tenant_id": original_tenant},
        )

    return canonical_id or document_id


async def compute_document_stats(
    session: AsyncSession, graph_client: GraphPort, document_id: str
) -> dict[str, int]:
    """Helper to compute document stats."""
    import logging

    from sqlalchemy import func, select

    from src.core.ingestion.domain.chunk import Chunk

    logger = logging.getLogger(__name__)

    # Chunk count (use original document_id — SQL chunks belong to the tenant's own doc)
    chunk_result = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    chunk_count = chunk_result.scalar() or 0

    # Resolve canonical default-tenant document ID for Neo4j graph lookups
    graph_doc_id = await resolve_graph_document_id(session, document_id)

    # Neo4j counts
    entity_count = 0
    relationship_count = 0
    community_count = 0
    similarity_count = 0

    try:
        # Entity count
        entity_res = await graph_client.execute_read(
            """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            MATCH (c)-[:MENTIONS]->(e:Entity)
            RETURN count(DISTINCT e) as c
            """,
            {"document_id": graph_doc_id},
        )
        if entity_res:
            entity_count = entity_res[0].get("c", 0)

        # Rel count
        rel_res = await graph_client.execute_read(
            """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            MATCH (c)-[:MENTIONS]->(s:Entity)-[r]->(t:Entity)
            WHERE exists {
                MATCH (d)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(t)
            }
            RETURN count(DISTINCT r) as c
            """,
            {"document_id": graph_doc_id},
        )
        if rel_res:
            relationship_count = rel_res[0].get("c", 0)

        # Community count
        comm_res = await graph_client.execute_read(
            """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            MATCH (c)-[:MENTIONS]->(e:Entity)-[:BELONGS_TO]->(comm:Community)
            RETURN count(DISTINCT comm) as c
            """,
            {"document_id": graph_doc_id},
        )
        if comm_res:
            community_count = comm_res[0].get("c", 0)

        # Similarity count
        sim_res = await graph_client.execute_read(
            """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)-[r:SIMILAR_TO]->(:Chunk)
            RETURN count(r) as c
            """,
            {"document_id": graph_doc_id},
        )
        if sim_res:
            similarity_count = sim_res[0].get("c", 0)

    except Exception as e:
        logger.warning(f"Failed to compute Neo4j stats for document {document_id}: {e}")

    return {
        "chunks": chunk_count,
        "entities": entity_count,
        "relationships": relationship_count,
        "communities": community_count,
        "similarities": similarity_count,
    }


async def compute_document_cost(session: AsyncSession, document_id: str) -> float:
    """
    Compute total ingestion cost for a document by aggregating usage logs.
    """
    from sqlalchemy import func, select

    from src.core.admin_ops.domain.usage import UsageLog

    # We use text() for JSON operator since SQLAlchemy core doesn't always support it cleanly in all drivers without casts
    # PostgreSQL: metadata_json ->> 'document_id'

    # Using func.json_extract_path_text for Postgres JSON/JSONB compatibility
    # This matches usage in admin/feedback.py
    query = select(func.sum(UsageLog.cost)).where(
        func.json_extract_path_text(UsageLog.metadata_json, "document_id") == document_id
    )

    # Ideally should filter by operation='embedding' too, but document_id check is specific enough

    result = await session.execute(query)
    total_cost = result.scalar()

    return float(total_cost) if total_cost else 0.0
