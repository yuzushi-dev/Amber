"""
Document API Routes
===================

Endpoints for document management.
Phase 1: Full implementation with async processing.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.config import settings
from src.core.models.document import Document
from src.core.state.machine import DocumentStatus
from src.core.storage.minio_client import MinIOClient
from src.core.services.ingestion import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


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
        created_at=document.created_at
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
