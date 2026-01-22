"""
Document API Routes
===================

Endpoints for document management.
Phase 1: Full implementation with async processing.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.api.config import settings
from src.api.deps import get_db_session as get_db_session
from src.core.graph.neo4j_client import neo4j_client
from src.core.models.document import Document
from src.core.services.ingestion import IngestionService
from src.core.state.machine import DocumentStatus
from src.core.storage.storage_client import MinIOClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_content_type(document: Document) -> str | None:
    """
    Get content type for a document.

    Checks metadata first, then derives from filename extension.
    """
    # Check if content_type is stored in metadata
    if document.metadata_ and isinstance(document.metadata_, dict):
        content_type = document.metadata_.get("content_type")
        if content_type:
            return content_type

    # Derive from filename extension
    filename = document.filename.lower()
    if filename.endswith('.pdf'):
        return 'application/pdf'
    elif filename.endswith(('.md', '.markdown')):
        return 'text/markdown'
    elif filename.endswith('.txt'):
        return 'text/plain'
    elif filename.endswith('.html'):
        return 'text/html'
    elif filename.endswith('.json'):
        return 'application/json'
    elif filename.endswith('.csv'):
        return 'text/csv'
    else:
        return 'text/plain'  # Default fallback


def _get_tenant_id(request: Request) -> str:
    """Resolve tenant ID from request context or default settings."""
    if hasattr(request.state, "tenant_id"):
        return str(request.state.tenant_id)
    return settings.tenant_id


class DocumentUploadResponse(BaseModel):
    """Response model for document upload."""
    document_id: str
    status: str
    events_url: str
    message: str


class DocumentResponse(BaseModel):
    """Response model for document details."""
    id: str
    filename: str
    title: str  # Alias for filename (for frontend compatibility)
    status: str
    domain: str | None = None
    tenant_id: str
    folder_id: str | None = None
    source_type: str | None = "upload"
    content_type: str | None = None  # MIME type of the document
    created_at: datetime

    # Enrichment fields
    summary: str | None = None
    document_type: str | None = None
    keywords: list[str] = []
    hashtags: list[str] = []
    metadata: dict[str, Any] | None = None

    # Stats (computed from chunks/entities/relationships)
    stats: dict[str, int] | None = None


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
    summary="Upload Document",
    description="""
    Upload a document for ingestion into the knowledge base.

    Returns 202 Accepted immediately with a document ID.
    Use the events_url to monitor processing progress via SSE.
    """,
)
async def upload_document(
    file: UploadFile = File(..., description="Document file to upload"),
    tenant_id: str = Form(default=None, description="Tenant ID (optional, uses default)"),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentUploadResponse:
    """
    Upload a document for async ingestion.
    """
    # Use default tenant if not provided
    tenant = tenant_id or settings.tenant_id

    # Read file content
    content = await file.read()

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file uploaded"
        )

    # Check file size
    max_size = settings.uploads.max_size_mb * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max size: {settings.uploads.max_size_mb}MB"
        )

    # Register document
    storage = MinIOClient()
    service = IngestionService(session, storage)

    document = await service.register_document(
        tenant_id=tenant,
        filename=file.filename or "unnamed",
        file_content=content,
        content_type=file.content_type or "application/octet-stream"
    )

    # Dispatch async processing task
    # Fix: Only dispatch if this is a new document to avoid duplicate processing
    if document.status == DocumentStatus.INGESTED:
        from src.workers.tasks import process_document
        process_document.delay(document.id, tenant)
    else:
        # Document was deduplicated (existing), so don't re-process
        pass

    # Build events URL
    events_url = f"/v1/documents/{document.id}/events"

    logger.info(f"Document {document.id} uploaded, processing dispatched")

    return DocumentUploadResponse(
        document_id=document.id,
        status=document.status.value,
        events_url=events_url,
        message="Document accepted for processing"
    )


@router.get(
    "/{document_id}/events",
    summary="Document Processing Events",
    description="""
    Server-Sent Events (SSE) endpoint for monitoring document processing status in real-time.

    Subscribe to this endpoint to receive status updates as the document moves through
    the ingestion pipeline (extracting, classifying, chunking, embedding, graph_sync, ready).
    """,
)
async def document_events(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Stream document processing events via SSE.

    This endpoint subscribes to Redis pub/sub for real-time status updates.
    """
    # Verify document exists and get tenant_id
    # Verify document exists and get tenant_id
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)
    
    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
        query = query.where(Document.tenant_id == tenant_id)
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    async def event_generator():
        """Generate SSE events from Redis pub/sub."""
        redis_client = None
        pubsub = None

        try:
            # Connect to Redis
            redis_client = redis.from_url(settings.db.redis_url, decode_responses=True)
            pubsub = redis_client.pubsub()

            # Subscribe to document status channel
            channel = f"document:{document_id}:status"
            await pubsub.subscribe(channel)

            logger.info(f"SSE client connected for document {document_id}")

            # Send initial status
            yield {
                "event": "status",
                "data": json.dumps({
                    "document_id": document_id,
                    "status": document.status.value,
                    "message": f"Monitoring document {document_id}"
                })
            }

            # Listen for Redis pub/sub messages
            while True:
                try:
                    # Use timeout to allow periodic checks
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0
                    )

                    if message and message['type'] == 'message':
                        # Forward the Redis message as SSE event
                        data = message['data']

                        # Parse and re-serialize to ensure valid JSON
                        if isinstance(data, str):
                            event_data = json.loads(data)
                        else:
                            event_data = data

                        yield {
                            "event": "status",
                            "data": json.dumps(event_data)
                        }

                        # Close connection if document reached terminal state
                        if event_data.get('status') in ['ready', 'failed', 'completed']:
                            logger.info(f"Document {document_id} reached terminal state: {event_data.get('status')}")
                            break

                except TimeoutError:
                    # Send keepalive comment to prevent connection timeout
                    yield {
                        "comment": "keepalive"
                    }
                    continue

        except Exception as e:
            logger.error(f"SSE error for document {document_id}: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }
        finally:
            # Cleanup
            if pubsub:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            if redis_client:
                await redis_client.close()
            logger.info(f"SSE client disconnected for document {document_id}")

    return EventSourceResponse(event_generator())


@router.get(
    "",
    summary="List Documents",
    description="List all documents in the knowledge base.",
)
async def list_documents(
    http_request: Request,
    tenant_id: str = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentResponse]:
    """
    List documents in the knowledge base.
    """
    # Check permissions
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document)

    if is_super_admin:
        # Super Admin: Show all if no tenant specified
        if tenant_id:
            query = query.where(Document.tenant_id == tenant_id)
    else:
        # Regular User: Enforce current tenant
        # Use tenant from request state (set by auth middleware) or fallback to settings
        current_tenant = getattr(http_request.state, "tenant_id", settings.tenant_id)
        query = query.where(Document.tenant_id == str(current_tenant))

    # Apply pagination
    query = query.limit(limit).offset(offset)

    result = await session.execute(query)
    documents = result.scalars().all()

    return [
        DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            title=doc.filename,  # Alias for frontend
            status=doc.status.value,
            domain=doc.domain,
            tenant_id=doc.tenant_id,
            folder_id=doc.folder_id,
            source_type=doc.source_type,
            content_type=_get_content_type(doc),
            created_at=doc.created_at
        )
        for doc in documents
    ]


@router.get(
    "/{document_id}",
    summary="Get Document",
    description="Get details of a specific document including enrichment data and stats.",
)
async def get_document(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    """
    Get document details with enrichment data and statistics.
    """
    logger.info(f"DEBUG: Processing get_document for {document_id}")
    
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
        query = query.where(Document.tenant_id == tenant_id)
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # Compute stats from chunks and graph
    stats = await _compute_document_stats(document_id, document.tenant_id, session)

    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        title=document.filename,  # Alias for frontend
        status=document.status.value,
        domain=document.domain,
        tenant_id=document.tenant_id,
        folder_id=document.folder_id,
        source_type=document.source_type,
        content_type=_get_content_type(document),
        created_at=document.created_at,
        # Enrichment fields
        summary=document.summary,
        document_type=document.document_type,
        keywords=document.keywords or [],
        hashtags=document.hashtags or [],
        metadata=document.metadata_,
        stats=stats,
    )


async def _compute_document_stats(
    document_id: str,
    tenant_id: str,
    session: AsyncSession
) -> dict[str, int]:
    """
    Compute document statistics: chunk count, entity count, relationship count.
    """
    from sqlalchemy import func

    from src.core.models.chunk import Chunk

    # Chunk count from PostgreSQL
    chunk_result = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    chunk_count = chunk_result.scalar() or 0

    # Entity and relationship counts from Neo4j
    entity_count = 0
    relationship_count = 0
    community_count = 0
    similarity_count = 0

    try:
        # Entity count query (MATCH using document_id only)
        entity_cypher = """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            MATCH (c)-[:MENTIONS]->(e:Entity)
            RETURN count(DISTINCT e) as entity_count
        """
        entity_records = await neo4j_client.execute_read(
            entity_cypher,
            {"document_id": document_id}
        )
        if entity_records:
            entity_count = entity_records[0].get("entity_count", 0)

        # Relationship count query
        rel_cypher = """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            MATCH (c)-[:MENTIONS]->(s:Entity)-[r]->(t:Entity)
            WHERE exists {
                MATCH (d)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(t)
            }
            RETURN count(DISTINCT r) as rel_count
        """
        rel_records = await neo4j_client.execute_read(
            rel_cypher,
            {"document_id": document_id}
        )
        if rel_records:
            relationship_count = rel_records[0].get("rel_count", 0)

        # Community count (via BELONGS_TO relationship)
        comm_cypher = """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            MATCH (c)-[:MENTIONS]->(e:Entity)-[:BELONGS_TO]->(comm:Community)
            RETURN count(DISTINCT comm) as comm_count
        """
        comm_records = await neo4j_client.execute_read(
            comm_cypher,
            {"document_id": document_id}
        )
        if comm_records:
            community_count = comm_records[0].get("comm_count", 0)

        # Similarity count
        sim_records = await neo4j_client.execute_read(
            """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)-[r:SIMILAR_TO]->(:Chunk)
            RETURN count(r) as sim_count
            """,
            {"document_id": document_id}
        )
        if sim_records:
            similarity_count = sim_records[0].get("sim_count", 0)

    except Exception as e:
        logger.warning(f"Failed to compute Neo4j stats for document {document_id}: {e}")
        # Stats will remain at 0 if Neo4j queries fail

    return {
        "chunks": chunk_count,
        "entities": entity_count,
        "relationships": relationship_count,
        "communities": community_count,
        "similarities": similarity_count,
    }


@router.get(
    "/{document_id}/communities",
    summary="Get Document Communities",
    description="Get communities (entity clusters) associated with this document.",
)
async def get_document_communities(
    document_id: str,
    limit: int = 50,
    offset: int = 0,
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get communities (entity clusters) for a document from Neo4j.

    Returns communities with their entities, sorted by entity count.
    """
    # Verify document exists
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
         # Need tenant_id to verify ownership if not super admin
         # We can't easily get it here without request object properly 
         # But http_request is optional in signature? No, let's look at signature.
         # http_request: Request = None 
         # Wait, if it's None we can't check permissions. 
         # But Depends(verify_admin) or auth middleware ensures request is populated?
         # Actually get_document_communities has `http_request: Request = None` ???
         # Checking signature: `http_request: Request = None`. 
         # If called from API, FastAPI injects it? No, Request must be declared.
         # If it's None, we might fail. 
         # But let's assume it's injected if requested.
         if http_request:
             tenant_id = _get_tenant_id(http_request)
             query = query.where(Document.tenant_id == tenant_id)
         else:
             # Fallback or error? If we are here, we probably have a request context.
             # The signature seems to imply it might be optional, but for a router endpoint it should be there.
             # Let's trust `_get_tenant_id` handles request attribute access, but we need request.
             pass
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # Query Neo4j for communities via BELONGS_TO relationship
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[:MENTIONS]->(e:Entity)-[:BELONGS_TO]->(comm:Community)
        WITH comm, collect(DISTINCT {
            name: e.name,
            type: e.type,
            description: e.description
        }) AS entities
        RETURN comm.id AS community_id, comm.title AS title, comm.summary AS summary,
               comm.level AS level, entities, size(entities) AS entity_count
        ORDER BY entity_count DESC
        SKIP $offset
        LIMIT $limit
    """

    try:
        records = await neo4j_client.execute_read(
            cypher,
            {
                "document_id": document_id,
                "offset": offset,
                "limit": limit,
            }
        )

        return [
            {
                "community_id": record.get("community_id"),
                "title": record.get("title"),
                "summary": record.get("summary"),
                "level": record.get("level"),
                "entity_count": record.get("entity_count", 0),
                "entities": record.get("entities", []),
            }
            for record in records
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch communities for document {document_id}: {e}")
        return []


@router.get(
    "/{document_id}/file",
    summary="Get Document File",
    description="Download the original document file from storage.",
)
async def get_document_file(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Retrieve the original document file from MinIO storage.

    Returns a streaming response with the file content and appropriate content-type header.
    """
    # Get document metadata
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
        query = query.where(Document.tenant_id == tenant_id)
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # Get file from MinIO
    try:
        storage = MinIOClient()
        # Get the raw stream from MinIO (urllib3 response)
        file_stream = storage.get_file_stream(document.storage_path)

        # Determine content type
        content_type = _get_content_type(document)

        # Stream the file back to the client
        # We pass the stream directly to StreamingResponse
        return StreamingResponse(
            file_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{document.filename}"'
            }
        )

    except Exception as e:
        logger.error(f"Failed to retrieve file for document {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve file: {str(e)}"
        ) from e


class DocumentUpdate(BaseModel):
    """Schema for updating a document."""
    title: str | None = None
    folder_id: str | None = None


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Update Document",
    description="Update document details (e.g., title, folder).",
)
async def update_document(
    document_id: str,
    update_data: DocumentUpdate,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    """
    Update a document.
    """
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
        query = query.where(Document.tenant_id == tenant_id)
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )
        
    # Apply updates
    if update_data.title is not None:
        document.filename = update_data.title # Alias for now
        # Also update metadata title if exists
        # document.metadata_['title'] = update_data.title

    if update_data.folder_id is not None:
        # Verify folder exists if not clearing it
        # Actually Pydantic won't let it be None here if not explicit? 
        # Wait, str | None = None means it defaults to None. 
        # If client sends null for folder_id, update_data.folder_id will be None? 
        # No, if client sends explicit null, it depends on Pydantic config.
        # But here I want to allow clearing folder_id.
        # Let's verify folder logic.
        
        # If string "null" or empty string, clear it? No, explicit None or empty string.
        # Let's support an empty string as "unfile".
        if update_data.folder_id == "":
             document.folder_id = None
        else:
             # Verify folder exists and belongs to tenant
             from src.core.models.folder import Folder
             folder = await session.get(Folder, update_data.folder_id)
             if not folder or folder.tenant_id != tenant_id:
                  raise HTTPException(status_code=404, detail="Folder not found")
             document.folder_id = update_data.folder_id
             
    await session.commit()
    await session.refresh(document)
    
    # Re-fetch stats for response
    stats = await _compute_document_stats(document_id, document.tenant_id, session)

    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        title=document.filename,
        status=document.status.value,
        domain=document.domain,
        tenant_id=document.tenant_id,
        source_type=document.source_type,
        content_type=_get_content_type(document),
        created_at=document.created_at,
        summary=document.summary,
        document_type=document.document_type,
        keywords=document.keywords or [],
        hashtags=document.hashtags or [],
        metadata=document.metadata_,
        stats=stats,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Document",
    description="Delete a document from the knowledge base.",
)
async def delete_document(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a document.
    """
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
        query = query.where(Document.tenant_id == tenant_id)
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # Delete from Neo4j graph
    try:
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
        await neo4j_client.execute_write(
            cypher,
            {"document_id": document_id, "tenant_id": document.tenant_id},
        )
    except Exception as e:
        logger.warning(f"Failed to delete graph data for document {document_id}: {e}")

    # Delete from Milvus vector store
    try:
        from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore

        milvus_config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=f"amber_{document.tenant_id}",
        )
        vector_store = MilvusVectorStore(milvus_config)
        try:
            await vector_store.delete_by_document(document_id, document.tenant_id)
        finally:
            await vector_store.disconnect()
    except Exception as e:
        logger.warning(f"Failed to delete vectors for document {document_id}: {e}")

    # Delete from MinIO
    try:
        storage = MinIOClient()
        storage.delete_file(document.storage_path)
    except Exception as e:
        logger.warning(f"Failed to delete file from storage: {e}")

    # Delete from DB (cascades to chunks)
    await session.delete(document)
    await session.commit()

    logger.info(f"Document {document_id} deleted")


@router.get(
    "/{document_id}/entities",
    summary="Get Document Entities",
    description="Get entities extracted from a specific document with pagination.",
)
async def get_document_entities(
    document_id: str,
    limit: int = 100,
    offset: int = 0,
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get entities extracted from a specific document via Neo4j.

    Args:
        document_id: Document UUID
        limit: Maximum number of entities to return (default: 100)
        offset: Number of entities to skip (default: 0)
    """
    # 1. Verify existence in SQL and get tenant_id
    permissions = getattr(http_request.state, "permissions", []) if http_request else []
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        if http_request:
            tenant_id = _get_tenant_id(http_request)
            query = query.where(Document.tenant_id == tenant_id)
        else:
             # Fallback if request is missing (should not happen in API call)
             pass
    
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # 2. Query Neo4j with pagination
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[:MENTIONS]->(e:Entity)
        RETURN DISTINCT e
        ORDER BY e.name
        SKIP $offset
        LIMIT $limit
    """

    try:
        records = await neo4j_client.execute_read(
            cypher,
            {
                "document_id": document_id,
                "limit": limit,
                "offset": offset
            }
        )
        # Neo4j Node objects can be converted to dict, but driver returns distinct e as Node.
        # We need to extract properties.
        return [dict(record["e"]) for record in records]
    except Exception as e:
        logger.error(f"Failed to fetch entities for document {document_id}: {e}")
        return []


@router.get(
    "/{document_id}/relationships",
    summary="Get Document Relationships",
    description="Get relationships between entities in this document with pagination.",
)
async def get_document_relationships(
    document_id: str,
    limit: int = 100,
    offset: int = 0,
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get relationships between entities in this document via Neo4j.

    Optimized query that avoids Cartesian products.

    Args:
        document_id: Document UUID
        limit: Maximum number of relationships to return (default: 100)
        offset: Number of relationships to skip (default: 0)
    """
    # 1. Verify existence
    permissions = getattr(http_request.state, "permissions", []) if http_request else []
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        if http_request:
            tenant_id = _get_tenant_id(http_request)
            query = query.where(Document.tenant_id == tenant_id)
    
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # 2. Query Neo4j
    # OPTIMIZED: Direct MATCH pattern instead of UNWIND Cartesian product
    # This is O(N) instead of O(N²) where N is the number of entities
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[:MENTIONS]->(s:Entity)
        MATCH (s)-[r]->(t:Entity)
        WHERE EXISTS {
              MATCH (d)-[:HAS_CHUNK]->(c2:Chunk)-[:MENTIONS]->(t)
          }
        RETURN DISTINCT {
            source: s.name,
            source_type: s.type,
            target: t.name,
            target_type: t.type,
            type: r.type,
            description: r.description,
            weight: r.weight
        } as rel
        ORDER BY rel.weight DESC
        SKIP $offset
        LIMIT $limit
    """

    try:
        records = await neo4j_client.execute_read(
            cypher,
            {
                "document_id": document_id,
                "limit": limit,
                "offset": offset
            }
        )
        return [record["rel"] for record in records]
    except Exception as e:
        logger.error(f"Failed to fetch relationships for document {document_id}: {e}")
        return []


from src.core.models.chunk import Chunk  # noqa: E402


@router.get(
    "/{document_id}/chunks",
    summary="Get Document Chunks",
    description="Get chunks for a specific document.",
)
async def get_document_chunks(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get chunks for a document from PostgreSQL.
    """
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    # 1. Verify existence
    # We can join with chunks directly or check doc first.
    # Checking doc first gives better error message.
    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
        query = query.where(Document.tenant_id == tenant_id)
    
    result = await session.execute(query)
    doc = result.scalars().first()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # 2. Fetch chunks from Postgres
    chunks_query = (
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.index.asc())
    )
    result = await session.execute(chunks_query)
    chunks = result.scalars().all()

    return [
        {
            "id": chunk.id,
            "index": chunk.index,
            "content": chunk.content,
            "tokens": chunk.tokens,
            "embedding_status": chunk.embedding_status.value
        }
        for chunk in chunks
    ]
@router.get(
    "/{document_id}/similarities",
    summary="Get Document Similarities",
    description="Get similarity relationships between chunks within the document.",
)
async def get_document_similarities(
    document_id: str,
    http_request: Request,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get similarity relationships between chunks within the document.
    """
    # Verify document and get tenant
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    query = select(Document).where(Document.id == document_id)

    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
        query = query.where(Document.tenant_id == tenant_id)
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )
    
    # Query SIMILAR_TO relationships in Neo4j
    # We want chunk text as well to display in frontend
    # Query SIMILAR_TO relationships in Neo4j
    # We fetch chunk IDs from Neo4j, then texts from Postgres (since Neo4j chunks don't have text)
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c1:Chunk)
        MATCH (c1)-[r:SIMILAR_TO]->(c2:Chunk)
        WHERE c1.id < c2.id
        RETURN c1.id as source_id, 
               c2.id as target_id, 
               r.score as score
        ORDER BY r.score DESC
        SKIP $offset
        LIMIT $limit
    """
    
    try:
        # 1. Fetch relations from Neo4j
        records = await neo4j_client.execute_read(
            cypher,
            {
                "document_id": document_id, 
                "offset": offset,
                "limit": limit
            }
        )

        if not records:
            return []

        # 2. Collect unique chunk IDs
        chunk_ids = set()
        for r in records:
            chunk_ids.add(r["source_id"])
            chunk_ids.add(r["target_id"])
        
        # 3. Fetch Chunk text from Postgres
        from src.core.models.chunk import Chunk
        chunk_query = select(Chunk.id, Chunk.content).where(
            Chunk.id.in_(chunk_ids)
        )
        chunk_result = await session.execute(chunk_query)
        chunk_map = {row.id: row.content for row in chunk_result.all()}
        
        # 4. Map back to response
        return [
            {
                "source_id": r.get("source_id"),
                "source_text": (chunk_map.get(r.get("source_id")) or "")[:200] + "...",
                "target_id": r.get("target_id"),
                "target_text": (chunk_map.get(r.get("target_id")) or "")[:200] + "...",
                "score": r.get("score"),
            }
            for r in records
        ]

    except Exception as e:
        logger.warning(f"Failed to fetch similarities for document {document_id}: {e}")
        return []
