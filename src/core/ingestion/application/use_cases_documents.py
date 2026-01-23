"""
Document Use Cases
==================

Application layer use cases for document operations.
These contain the business logic extracted from route handlers.
"""

from dataclasses import dataclass
from typing import Protocol, Any

import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Protocols for dependencies
# -----------------------------------------------------------------------------

class StoragePort(Protocol):
    """Port for storage operations."""
    
    def upload_file(
        self, object_name: str, data, length: int, content_type: str
    ) -> None:
        """Upload a file to storage."""
        ...
    
    def get_file(self, object_name: str) -> bytes:
        """Get file content from storage."""
        ...


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

from src.core.ingestion.domain.ports.dispatcher import TaskDispatcher
from src.core.events.dispatcher import EventDispatcher

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
        session: AsyncSession,
        storage: StoragePort,
        max_size_bytes: int,
        neo4j_client: Any,
        vector_store: Any,
        task_dispatcher: TaskDispatcher | None = None,
        event_dispatcher: EventDispatcher | None = None,
    ):
        """
        Initialize the use case.
        
        Args:
            session: Database session for the transaction.
            storage: Storage adapter for file operations.
            max_size_bytes: Maximum allowed file size.
            neo4j_client: Neo4j client instance.
            vector_store: Vector store instance.
            task_dispatcher: Dispatcher for background jobs.
        """
        self._session = session
        self._storage = storage
        self._max_size_bytes = max_size_bytes
        self._neo4j_client = neo4j_client
        self._vector_store = vector_store
        self._task_dispatcher = task_dispatcher
        self._event_dispatcher = event_dispatcher
    
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
        
        # Register document
        from src.core.ingestion.application.ingestion_service import IngestionService
        from src.core.state.machine import DocumentStatus
        from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
        from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import PostgresTenantRepository
        from src.core.ingestion.infrastructure.uow.postgres_uow import PostgresUnitOfWork
        
        repository = PostgresDocumentRepository(self._session)
        tenant_repo = PostgresTenantRepository(self._session)
        uow = PostgresUnitOfWork(self._session)
        
        service = IngestionService(
            document_repository=repository, 
            tenant_repository=tenant_repo,
            unit_of_work=uow,
            storage_client=self._storage,
            neo4j_client=self._neo4j_client,
            vector_store=self._vector_store,
            event_dispatcher=self._event_dispatcher,
        )
        document = await service.register_document(
            tenant_id=request.tenant_id,
            filename=request.filename,
            file_content=request.content,
            content_type=request.content_type,
        )
        
        # Commit transaction
        await self._session.commit()
        await self._session.refresh(document)
        
        # Dispatch async processing if new document
        is_duplicate = document.status != DocumentStatus.INGESTED
        if not is_duplicate:
            if self._task_dispatcher:
                await self._task_dispatcher.dispatch("src.workers.tasks.process_document", args=[document.id, request.tenant_id])
            else:
                # No dispatcher - this is a test or sync execution scenario
                # Caller must handle processing separately
                logger.warning("No TaskDispatcher available, document not queued for async processing")
        
        return UploadDocumentResult(
            document_id=document.id,
            status=document.status.value,
            is_duplicate=is_duplicate,
            message="Document accepted for processing" if not is_duplicate else "Document deduplicated",
        )


class GraphPort(Protocol):
    """Port for graph database operations."""
    
    async def execute_write(self, query: str, parameters: dict) -> None:
        """Execute a write query."""
        ...

    async def execute_read(self, query: str, parameters: dict) -> list[dict]:
        """Execute a read query."""
        ...


class VectorStorePort(Protocol):
    """Port for vector store operations."""
    
    async def delete_by_document(self, document_id: str, tenant_id: str) -> bool:
        """Delete vectors for a document."""
        ...
        
    async def disconnect(self) -> None:
        """Close connection."""
        ...


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
        vector_store_factory, # Callable returning VectorStorePort
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
        
        # We determine storage path and tenant_id
        # If document not in Postgres, we use request info for best-effort cleanup
        tenant_id = document.tenant_id if document else request.tenant_id
        storage_path = document.storage_path if document else f"{tenant_id}/{request.document_id}/"

        # 2. Delete from Neo4j (Hardened Query)
        try:
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
        except Exception as e:
            logger.warning(f"Failed to delete graph data for document {request.document_id}: {e}")

        # 3. Delete from Milvus
        try:
            vector_store = self._vector_store_factory(tenant_id)
            try:
                await vector_store.delete_by_document(request.document_id, tenant_id)
                logger.info(f"Cleaned up Milvus data for document {request.document_id}")
            finally:
                if hasattr(vector_store, 'disconnect'):
                    await vector_store.disconnect()
        except Exception as e:
             logger.warning(f"Failed to delete vectors for document {request.document_id}: {e}")

        # 4. Delete from MinIO
        try:
            if hasattr(self._storage, 'delete_file'):
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
        
        return DeleteDocumentResult(document_id=request.document_id)


# -----------------------------------------------------------------------------
# Get Document Use Case
# -----------------------------------------------------------------------------

@dataclass
class GetDocumentRequest:
    """Request DTO for getting a document."""
    document_id: str
    tenant_id: str
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
        from src.core.ingestion.domain.document import Document
        
        # 1. Fetch Request
        query = select(Document).where(Document.id == request.document_id)
        if not request.is_super_admin:
            query = query.where(Document.tenant_id == request.tenant_id)
            
        result = await self._session.execute(query)
        document = result.scalars().first()
        
        if not document:
             raise LookupError(f"Document {request.document_id} not found")

        # 2. Compute Stats
        stats = await compute_document_stats(self._session, self._graph_client, document.id)

        # 3. Determine Content Type
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
            else:
                # Verify folder exists
                folder = await self._session.get(Folder, request.folder_id)
                # Check folder ownership if strictly enforced or implied by access
                if not folder or (not request.is_super_admin and folder.tenant_id != request.tenant_id):
                     # If super admin, we expect folder to be valid. 
                     # Ideally we should check if folder belongs to same tenant as document anyway.
                     if not folder or folder.tenant_id != document.tenant_id:
                         raise LookupError("Folder not found or invalid")
                
                document.folder_id = request.folder_id
        
        await self._session.commit()
        await self._session.refresh(document)
        
        # 3. Compute Stats & Return
        stats = await compute_document_stats(self._session, self._graph_client, document.id)
        
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
        )


async def compute_document_stats(
    session: AsyncSession,
    graph_client: GraphPort,
    document_id: str
) -> dict[str, int]:
    """Helper to compute document stats."""
    from sqlalchemy import func, select
    from src.core.ingestion.domain.chunk import Chunk
    import logging
    logger = logging.getLogger(__name__)

    # Chunk count
    chunk_result = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    chunk_count = chunk_result.scalar() or 0

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
            {"document_id": document_id}
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
            {"document_id": document_id}
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
            {"document_id": document_id}
        )
        if comm_res:
            community_count = comm_res[0].get("c", 0)

        # Similarity count
        sim_res = await graph_client.execute_read(
            """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)-[r:SIMILAR_TO]->(:Chunk)
            RETURN count(r) as c
            """,
            {"document_id": document_id}
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
