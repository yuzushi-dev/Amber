"""
Document Use Cases
==================

Application layer use cases for document operations.
These contain the business logic extracted from route handlers.
"""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


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
    ):
        """
        Initialize the use case.
        
        Args:
            session: Database session for the transaction.
            storage: Storage adapter for file operations.
            max_size_bytes: Maximum allowed file size.
        """
        self._session = session
        self._storage = storage
        self._max_size_bytes = max_size_bytes
    
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
        from src.core.services.ingestion import IngestionService
        from src.core.state.machine import DocumentStatus
        
        service = IngestionService(self._session, self._storage)
        document = await service.register_document(
            tenant_id=request.tenant_id,
            filename=request.filename,
            file_content=request.content,
            content_type=request.content_type,
        )
        
        # Dispatch async processing if new document
        is_duplicate = document.status != DocumentStatus.INGESTED
        if not is_duplicate:
            from src.workers.tasks import process_document
            process_document.delay(document.id, request.tenant_id)
        
        return UploadDocumentResult(
            document_id=document.id,
            status=document.status.value,
            is_duplicate=is_duplicate,
            message="Document accepted for processing" if not is_duplicate else "Document deduplicated",
        )
