
import pytest
import unittest.mock
from unittest.mock import AsyncMock, MagicMock
from src.core.ingestion.application.ingestion_service import IngestionService
from src.core.generation.domain.provider_models import QuotaExceededError
from src.core.state.machine import DocumentStatus
# Import models to ensure SQLAlchemy registry is populated
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
import json

@pytest.mark.asyncio
async def test_process_document_handles_quota_exceeded():
    # Setup
    document_repo = AsyncMock()
    uow = AsyncMock()
    
    # Mock Document
    mock_doc = MagicMock()
    mock_doc.id = "doc_123"
    mock_doc.status = DocumentStatus.EMBEDDING
    document_repo.get.return_value = mock_doc

    # Patch dependencies
    # Patch global import (used in __init__)
    with unittest.mock.patch('src.core.ingestion.application.ingestion_service.EmbeddingService') as MockGlobalEmbeddingService, \
         unittest.mock.patch('src.core.retrieval.application.embeddings_service.EmbeddingService') as MockLocalEmbeddingService, \
         unittest.mock.patch('src.core.retrieval.application.sparse_embeddings_service.SparseEmbeddingService') as MockSparse, \
         unittest.mock.patch('src.core.generation.application.intelligence.classifier.DomainClassifier') as MockClassifier, \
         unittest.mock.patch('src.core.generation.domain.ports.provider_factory.build_provider_factory') as MockBuildFactory:
        
        # Setup Factory
        mock_factory = MagicMock()
        mock_provider = AsyncMock()  # Provider needs to be an object, not a string
        mock_factory.get_embedding_provider.return_value = mock_provider 
        MockBuildFactory.return_value = mock_factory
        
        # Setup Embedding Mock (Local one is used in process_document)
        embedding_instance = MockLocalEmbeddingService.return_value
        embedding_instance.embed_texts.side_effect = QuotaExceededError("Quota exceeded", provider="openai")
        
        # Setup Classifier Mock (so it doesn't crash on init)
        mock_classifier_instance = MagicMock()
        mock_classifier_instance.classify = AsyncMock()
        mock_classifier_instance.classify.return_value.value = "test_domain"
        mock_classifier_instance.close = AsyncMock() 
        MockClassifier.return_value = mock_classifier_instance

        # Setup Content Extractor Mock
        mock_extractor = AsyncMock()
        mock_extraction_result = MagicMock()
        mock_extraction_result.content = "Filtered content"
        mock_extraction_result.metadata = {}
        mock_extraction_result.extractor_used = "text"
        mock_extractor.extract.return_value = mock_extraction_result

        # Mock Settings
        mock_settings = MagicMock()
        mock_settings.default_embedding_provider = "openai"
        mock_settings.default_embedding_model = "text-embedding-3-small"
        mock_settings.embedding_dimensions = 1536
        mock_settings.openai_api_key = "test-key"
        mock_settings.ollama_base_url = "http://localhost:11434"

        # Mock Tenant Repo
        tenant_repo = AsyncMock()
        mock_tenant = MagicMock()
        mock_tenant.config = {"embedding_provider": "openai"}
        tenant_repo.get.return_value = mock_tenant

        # Initialize Service
        service = IngestionService(
            document_repository=document_repo,
            tenant_repository=tenant_repo,
            unit_of_work=uow,
            storage_client=AsyncMock(),
            neo4j_client=AsyncMock(),
            vector_store=AsyncMock(),
            content_extractor=mock_extractor,
            settings=mock_settings,
        )
        
        # Execution
        with pytest.raises(QuotaExceededError):
            await service.process_document("doc_123")
            
        # Verification
        document_repo.save.assert_called_with(mock_doc)
        uow.commit.assert_called()
        
        assert mock_doc.status == DocumentStatus.FAILED
        assert mock_doc.error_message is not None
        
        # Parse error
        error_data = json.loads(mock_doc.error_message)
        assert error_data["code"] == "quota_exceeded"
        assert error_data["provider"] == "Openai"

