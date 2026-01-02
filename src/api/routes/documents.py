"""
Document API Routes
===================

Endpoints for document management.
Phase 1: Full implementation with async processing.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.config import settings
from src.core.models.document import Document
from src.core.state.machine import DocumentStatus
from src.core.storage.minio_client import MinIOClient
from src.core.services.ingestion import IngestionService
from src.core.graph.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_content_type(document: Document) -> Optional[str]:
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
    domain: Optional[str] = None
    tenant_id: str
    source_type: Optional[str] = "upload"
    content_type: Optional[str] = None  # MIME type of the document
    created_at: datetime


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
    from src.workers.tasks import process_document
    process_document.delay(document.id, tenant)
    
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
    "",
    summary="List Documents",
    description="List all documents in the knowledge base.",
)
async def list_documents(
    tenant_id: str = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentResponse]:
    """
    List documents in the knowledge base.
    """
    tenant = tenant_id or settings.tenant_id
    
    query = select(Document).where(
        Document.tenant_id == tenant
    ).limit(limit).offset(offset)
    
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
            source_type=doc.source_type,
            content_type=_get_content_type(doc),
            created_at=doc.created_at
        )
        for doc in documents
    ]


@router.get(
    "/{document_id}",
    summary="Get Document",
    description="Get details of a specific document.",
)
async def get_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    """
    Get document details.
    """
    query = select(Document).where(Document.id == document_id)
    result = await session.execute(query)
    document = result.scalars().first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )
    
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        title=document.filename,  # Alias for frontend
        status=document.status.value,
        domain=document.domain,
        tenant_id=document.tenant_id,
        source_type=document.source_type,
        content_type=_get_content_type(document),
        created_at=document.created_at
    )


@router.get(
    "/{document_id}/file",
    summary="Get Document File",
    description="Download the original document file from storage.",
)
async def get_document_file(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Retrieve the original document file from MinIO storage.

    Returns a streaming response with the file content and appropriate content-type header.
    """
    # Get document metadata
    query = select(Document).where(Document.id == document_id)
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
        file_data = storage.get_file(document.storage_path)

        # Determine content type
        content_type = _get_content_type(document)

        # Stream the file back to the client
        return StreamingResponse(
            file_data,
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
        )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Document",
    description="Delete a document from the knowledge base.",
)
async def delete_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a document.
    """
    query = select(Document).where(Document.id == document_id)
    result = await session.execute(query)
    document = result.scalars().first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )
    
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
    session: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """
    Get entities extracted from a specific document via Neo4j.

    Args:
        document_id: Document UUID
        limit: Maximum number of entities to return (default: 100)
        offset: Number of entities to skip (default: 0)
    """
    # 1. Verify existence in SQL and get tenant_id
    query = select(Document).where(Document.id == document_id)
    result = await session.execute(query)
    document = result.scalars().first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # 2. Query Neo4j with pagination
    cypher = """
        MATCH (d:Document {id: $document_id, tenant_id: $tenant_id})-[:HAS_CHUNK]->(c:Chunk)
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
                "tenant_id": document.tenant_id,
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
    session: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """
    Get relationships between entities in this document via Neo4j.

    Optimized query that avoids Cartesian products.

    Args:
        document_id: Document UUID
        limit: Maximum number of relationships to return (default: 100)
        offset: Number of relationships to skip (default: 0)
    """
    # 1. Verify existence
    query = select(Document).where(Document.id == document_id)
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
        MATCH (d:Document {id: $document_id, tenant_id: $tenant_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[:MENTIONS]->(s:Entity)
        MATCH (s)-[r:RELATED_TO]->(t:Entity)
        WHERE t.tenant_id = $tenant_id
          AND EXISTS {
              MATCH (d)-[:HAS_CHUNK]->(c2:Chunk)-[:MENTIONS]->(t)
          }
        RETURN DISTINCT {
            source: s.name,
            target: t.name,
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
                "tenant_id": document.tenant_id,
                "limit": limit,
                "offset": offset
            }
        )
        return [record["rel"] for record in records]
    except Exception as e:
        logger.error(f"Failed to fetch relationships for document {document_id}: {e}")
        return []
