"""
Integration Test: Ingestion Flow
=================================

Verifies document registration, storage, and database persistence.
"""

import pytest
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.services.ingestion import IngestionService
from src.core.storage.storage_client import MinIOClient
from src.core.models.document import Document
from src.core.models.chunk import Chunk
from src.core.state.machine import DocumentStatus

# Helper to clear data
async def clean_database(session: AsyncSession):
    await session.execute(text("DELETE FROM chunks"))
    await session.execute(text("DELETE FROM documents"))
    await session.commit()

@pytest.mark.asyncio
async def test_register_document_flow(db_session: AsyncSession, minio_container):
    # Setup
    tenant_id = f"test_tenant_{uuid.uuid4().hex[:8]}"
    filename = "test_doc.txt"
    content = b"Hello, World! This is a test document."
    
    # Clean DB
    # await clean_database(db_session) # Don't wipe everything if concurrent tests
    
    # Initialize Service
    from src.api.config import settings
    # Configure settings to use the test container
    settings.minio.host = minio_container.get_container_host_ip()
    settings.minio.port = int(minio_container.get_exposed_port(9000))
    settings.minio.secure = False
    settings.minio.access_key = "minioadmin"
    settings.minio.secret_key = "minioadmin"
    
    storage = MinIOClient()
    # Ensure bucket exists (handling this in service/client implicitly or explicitly)
    # The client.ensure_bucket_exists() is called in upload_file()
    
    service = IngestionService(db_session, storage)
    
    # 1. Register Document
    doc = await service.register_document(
        tenant_id=tenant_id,
        filename=filename,
        file_content=content
    )
    
    assert doc.id.startswith("doc_")
    assert doc.filename == filename
    assert doc.status == DocumentStatus.INGESTED
    assert doc.tenant_id == tenant_id
    
    # 2. Verify Storage
    downloaded_content = storage.get_file(doc.storage_path)
    assert downloaded_content == content
    
    # 3. Verify Database Persistence (Refetch)
    await db_session.refresh(doc)
    assert doc.created_at is not None
    
    # 4. Verify Idempotency (Register same file again)
    doc2 = await service.register_document(
        tenant_id=tenant_id,
        filename=filename,
        file_content=content
    )
    
    assert doc2.id == doc.id
    assert doc2.updated_at == doc.updated_at # Assuming no update on dedupe
    
    # Cleanup
    # storage.delete_file(doc.storage_path)
    # await db_session.delete(doc)
    # await db_session.commit()
