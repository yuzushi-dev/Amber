"""
Domain Classification Integration Test
======================================

Verifies the domain classifier and ingestion integration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.generation.application.intelligence.classifier import DomainClassifier
from src.core.generation.application.intelligence.strategies import DocumentDomain, get_strategy
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document
from src.core.ingestion.application.ingestion_service import IngestionService
from src.core.state.machine import DocumentStatus


@pytest.mark.asyncio
async def test_domain_classifier_logic():
    """Test the heuristic logic (mock LLM behavior)."""
    classifier = DomainClassifier()

    # Test Technical
    domain = await classifier.classify("def my_function(): return True")
    assert domain == DocumentDomain.TECHNICAL

    # Test Legal
    domain = await classifier.classify("This agreement is entered into by and between...")
    assert domain == DocumentDomain.LEGAL

    # Test General
    domain = await classifier.classify("Once upon a time in a generic text...")
    assert domain == DocumentDomain.GENERAL

    await classifier.close()

@pytest.mark.asyncio
async def test_strategy_mapping():
    """Test that domains map to correct strategies."""
    strategy = get_strategy("legal")
    assert strategy.chunk_size == 1000
    assert strategy.chunk_overlap == 100

    strategy = get_strategy("technical")
    assert strategy.chunk_size == 800

@pytest.mark.asyncio
async def test_ingestion_integration_classification(db_session):
    """
    Verify IngestionService.process_document invokes classification.
    We mock the storage and classifier to focus on the flow.
    """
    from src.core.ingestion.domain.ports.document_repository import DocumentRepository
    from src.core.ingestion.domain.document import Document
    from src.core.tenants.domain.tenant import Tenant
    from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import PostgresTenantRepository
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
    # from src.core.database.unit_of_work import SqlAlchemyUnitOfWork # Not used
    
    import uuid
    
    # Create tenant first
    tenant_id = str(uuid.uuid4())
    tenant = Tenant(id=tenant_id, name="Test Tenant")
    db_session.add(tenant)
    await db_session.commit()
    
    # Setup mocks for external dependencies
    mock_storage = MagicMock()
    mock_response = MagicMock()
    mock_response.read.return_value = b"def code(): pass"  # Technical content
    mock_storage.get_file.return_value = mock_response
    mock_storage.upload_file = AsyncMock(return_value="storage/path/code.py")
    
    mock_neo4j = MagicMock()
    mock_neo4j.execute_write = AsyncMock(return_value=[])
    
    mock_vector_store = MagicMock()
    mock_vector_store.insert = AsyncMock(return_value=None)
    mock_vector_store.upsert_chunks = AsyncMock(return_value=None)
    
    # Create repositories
    doc_repo = PostgresDocumentRepository(db_session)
    tenant_repo = PostgresTenantRepository(db_session)
    uow = MagicMock()
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    # Mock wrapper for provider factory
    mock_factory = MagicMock()
    mock_provider = MagicMock()
    mock_provider.embed = AsyncMock(return_value=MagicMock()) # Ensure awaitable
    mock_provider.count_tokens = AsyncMock(return_value=10)
    mock_factory.get_embedding_provider.return_value = mock_provider
    mock_factory.get_llm_provider.return_value = mock_provider
    
    from src.core.generation.domain.ports.provider_factory import set_provider_factory
    set_provider_factory(mock_factory)

    try:
        # Create service with all required dependencies
        service = IngestionService(
            document_repository=doc_repo,
            tenant_repository=tenant_repo,
            unit_of_work=uow,
            storage_client=mock_storage,
            neo4j_client=mock_neo4j,
            vector_store=mock_vector_store,
            task_dispatcher=None,
            event_dispatcher=None,
            vector_store_factory=None,
        )
        
        # Pre-seed document in DB
        doc_id = str(uuid.uuid4())
        doc = Document(
            id=doc_id, 
            tenant_id=tenant_id, 
            filename="code.py", 
            status=DocumentStatus.INGESTED, 
            content_hash=str(uuid.uuid4()), 
            storage_path="path"
        )
        db_session.add(doc)
        await db_session.commit()
        # Mock extraction result
        mock_extractor_result = MagicMock()
        mock_extractor_result.content = "def code(): pass"
        mock_extractor_result.extractor_used = "test"
        mock_extractor_result.confidence = 1.0
        mock_extractor_result.metadata = {}
        mock_extractor_result.extraction_time_ms = 10
        
        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=mock_extractor_result)

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.default_embedding_model = "text-embedding-3-small"
        mock_settings.default_embedding_provider = "openai"
        mock_settings.embedding_dimensions = 1536
        mock_settings.openai_api_key = "test-key"

        # Re-create service with extractor
        service = IngestionService(
            document_repository=doc_repo,
            tenant_repository=tenant_repo,
            unit_of_work=uow,
            storage_client=mock_storage,
            neo4j_client=mock_neo4j,
            vector_store=mock_vector_store,
            content_extractor=mock_extractor,
            settings=mock_settings,
            task_dispatcher=None,
            event_dispatcher=None,
            vector_store_factory=None,
        )

        # Run process
        await service.process_document(doc_id)
            
    finally:
        set_provider_factory(None)

    # Verify DB state
    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.READY
    assert doc.domain == DocumentDomain.TECHNICAL

    # Verify Chunk metadata
    from sqlalchemy import select
    result = await db_session.execute(select(Chunk).where(Chunk.document_id == doc_id))
    chunk = result.scalars().first()

    assert chunk is not None
    assert chunk.metadata_["domain"] == "technical"
