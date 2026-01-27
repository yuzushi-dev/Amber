"""
Integration Test: Ingestion Flow
=================================

Verifies document registration, storage, and database persistence.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ingestion.application.ingestion_service import IngestionService
from src.core.state.machine import DocumentStatus
from unittest.mock import AsyncMock
from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient


# Helper to clear data
async def clean_database(session: AsyncSession):
    await session.execute(text("DELETE FROM chunks"))
    await session.execute(text("DELETE FROM documents"))
    await session.commit()

@pytest.mark.asyncio
async def test_register_document_flow(db_session: AsyncSession):
    # Setup
    tenant_id = f"test_tenant_{uuid.uuid4().hex[:8]}"
    filename = "test_doc.txt"
    content = b"Hello, World! This is a test document."

    # Clean DB
    # await clean_database(db_session) # Don't wipe everything if concurrent tests

    # Initialize Service
    # Use default settings which point to localhost MinIO
    from src.api.config import settings

    storage = MinIOClient()
    # Ensure bucket exists (handling this in service/client implicitly or explicitly)
    # The client.ensure_bucket_exists() is called in upload_file()

    # Initialize Repositories & UoW
    # Initialize Repositories & UoW
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
    from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import PostgresTenantRepository
    from src.core.database.unit_of_work import SqlAlchemyUnitOfWork
    from unittest.mock import MagicMock
    
    doc_repo = PostgresDocumentRepository(db_session)
    tenant_repo = PostgresTenantRepository(db_session)
    # SqlAlchemyUnitOfWork expects (session_factory, tenant_id, is_super_admin)
    # But here we want a simple UoW that wraps the EXISTING db_session.
    # The real implementation creates new sessions.
    # For testing, we might want to mock UoW or assume we pass a session factory that yields current session.
    
    # Mock UoW for invalid arguments or misuse?
    # IngestionService expects `unit_of_work.commit()` to be awaitable.
    
    # Let's use a mock UoW that simulates commit on the db_session.
    uow = MagicMock()
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    
    # Mock provider factory
    from unittest.mock import MagicMock
    mock_factory = MagicMock()
    mock_provider = MagicMock()
    mock_factory.get_embedding_provider.return_value = mock_provider
    mock_factory.get_llm_provider.return_value = mock_provider
    
    from src.core.generation.domain.ports.provider_factory import set_provider_factory
    set_provider_factory(mock_factory)

    try:
        service = IngestionService(
            document_repository=doc_repo,
            tenant_repository=tenant_repo,
            unit_of_work=uow,
            storage_client=storage,
            neo4j_client=MagicMock(), # Not used for registration
            vector_store=None,
        )
    
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
    finally:
        set_provider_factory(None)

    # Cleanup
    # storage.delete_file(doc.storage_path)
    # await db_session.delete(doc)
    # await db_session.commit()
