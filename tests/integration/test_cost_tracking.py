import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.admin_ops.domain.usage import UsageLog
from src.core.ingestion.application.use_cases_documents import compute_document_stats, compute_document_cost
from src.core.ingestion.domain.document import Document
from src.core.ingestion.application.ingestion_service import IngestionService
from src.core.state.machine import DocumentStatus

@pytest.mark.asyncio
async def test_compute_document_cost_aggregation(db_session: AsyncSession):
    """
    Verify that compute_document_cost correctly aggregates costs 
    from usage_logs with matching document_id in metadata.
    """
    doc_id = f"doc_test_cost_{uuid.uuid4().hex}"
    
    # 1. Create Usage Logs
    # Note: We rely on the 'cleanup_test_tenant' global fixture to wipe this tenant.
    test_tenant = "integration_test_tenant"
    
    log1 = UsageLog(
        tenant_id=test_tenant,
        provider="openai",
        model="text-embedding-3-small",
        operation="embedding",
        cost=0.005,
        metadata_json={"document_id": doc_id, "chunk_index": 0}
    )
    log2 = UsageLog(
        tenant_id=test_tenant,
        provider="openai",
        model="text-embedding-3-small",
        operation="embedding",
        cost=0.003,
        metadata_json={"document_id": doc_id, "chunk_index": 1}
    )
    log3 = UsageLog(
        tenant_id=test_tenant,
        provider="openai",
        model="gpt-4",
        operation="generation",
        cost=0.10,
        metadata_json={"document_id": "other_doc"} # Should be ignored
    )
    
    db_session.add_all([log1, log2, log3])
    await db_session.commit()
    
    # 2. Compute Cost
    total_cost = await compute_document_cost(db_session, doc_id)
    
    # 3. Assert
    # Floating point comparison
    assert abs(total_cost - 0.008) < 1e-9
    
    # Verify non-existent doc returns 0
    zero_cost = await compute_document_cost(db_session, "non_existent")
    assert zero_cost == 0.0


@pytest.mark.asyncio
async def test_ingestion_passes_metadata(db_session: AsyncSession):
    """
    Verify that IngestionService passes document_id in metadata to EmbeddingService.
    """
    # Setup Mocks
    mock_repo = AsyncMock()
    mock_tenant_repo = AsyncMock()
    mock_uow = AsyncMock()
    mock_storage = MagicMock()
    mock_neo4j = MagicMock()
    mock_vector = AsyncMock()
    
    # Mock Document
    doc = Document(
        id="doc_123",
        tenant_id="tenant_1",
        filename="test.txt",
        status=DocumentStatus.INGESTED,
        storage_path="path/to/test.txt"
    )
    doc.status = DocumentStatus.INGESTED
    
    # Mock Repository Returns
    mock_repo.get.return_value = doc
    mock_repo.update_status.return_value = True
    
    # Mock Extraction Result
    mock_extractor = AsyncMock()
    mock_extractor_result = MagicMock()
    mock_extractor_result.content = "Test content"
    mock_extractor_result.metadata = {}
    mock_extractor.extract.return_value = mock_extractor_result
    
    # Patch factories at source since they are imported locally
    with patch("src.core.generation.domain.ports.provider_factory.build_provider_factory") as MockBuildFactory, \
         patch("src.core.generation.domain.ports.provider_factory.get_provider_factory") as MockGetFactory, \
         patch("src.core.generation.application.intelligence.classifier.DomainClassifier") as MockClassifier, \
         patch("src.core.ingestion.application.ingestion_service.SemanticChunker") as MockChunker, \
         patch("src.core.ingestion.application.ingestion_service.EmbeddingService") as MockEmbeddingService, \
         patch("src.core.retrieval.application.embeddings_service.EmbeddingService") as MockGlobalEmbeddingService, \
         patch("src.core.retrieval.application.sparse_embeddings_service.SparseEmbeddingService"), \
         patch("src.core.graph.application.processor.GraphProcessor"):
         
        # Ensure global import is also mocked (for local imports in process_document)
        MockGlobalEmbeddingService.return_value = MockEmbeddingService.return_value
        
        # Configure Mock Tenant Repo to avoid AsyncMock config issues
        mock_tenant = MagicMock()
        mock_tenant.config = {}
        mock_tenant_repo.get.return_value = mock_tenant
            
        # Configure Factory Mocks
        mock_factory = MagicMock()
        mock_provider = MagicMock()
        mock_factory.get_embedding_provider.return_value = mock_provider
        MockBuildFactory.return_value = mock_factory
        MockGetFactory.return_value = mock_factory

        # Configure settings mock
        mock_settings = MagicMock()
        mock_settings.default_embedding_model = "text-embedding-3-small"
        mock_settings.default_embedding_provider = "openai"
        mock_settings.embedding_dimensions = 1536
        mock_settings.openai_api_key = "test-key"

        # Initialize Service (INSIDE patch to ensure mocked dependencies)
        service = IngestionService(
            document_repository=mock_repo,
            tenant_repository=mock_tenant_repo,
            unit_of_work=mock_uow,
            storage_client=mock_storage,
            neo4j_client=mock_neo4j,
            vector_store=mock_vector,
            content_extractor=mock_extractor,
            settings=mock_settings
        )

        # Configure internal mocks
        mock_classifier_instance = MockClassifier.return_value
        mock_classifier_instance.classify = AsyncMock()
        mock_classifier_instance.classify.return_value = MagicMock(value="general")
        mock_classifier_instance.close = AsyncMock()
        
        mock_chunker_instance = MockChunker.return_value
        chunk_data = MagicMock()
        chunk_data.index = 0
        chunk_data.content = "Test content chunk"
        chunk_data.token_count = 5
        chunk_data.metadata = {}
        mock_chunker_instance.chunk.return_value = [chunk_data]
        
        mock_filesvc_instance = MockEmbeddingService.return_value
        mock_filesvc_instance.embed_texts = AsyncMock()
        mock_filesvc_instance.embed_texts.return_value = ([[0.1]*1536], MagicMock())
        
        # Run
        try:
            await service.process_document("doc_123")
        except Exception:
            pass
            
        # Verify
        args, kwargs = mock_filesvc_instance.embed_texts.call_args
        assert "metadata" in kwargs
        assert kwargs["metadata"] == {"document_id": "doc_123"}
