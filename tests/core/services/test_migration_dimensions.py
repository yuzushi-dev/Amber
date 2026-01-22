import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.core.services.migration import EmbeddingMigrationService
from src.core.services.embeddings import EmbeddingService

@pytest.fixture
def mock_session():
    return AsyncMock()

@pytest.fixture
def service(mock_session):
    return EmbeddingMigrationService(mock_session)

@pytest.mark.asyncio
async def test_resolve_dimensions_known_model(service):
    """Test that known models from hardcoded list return correct dimensions without calling provider."""
    # Based on the MODEL_DIMENSIONS dict in the original file
    dims = await service._resolve_dimensions("openai", "text-embedding-3-small")
    assert dims == 1536

    dims = await service._resolve_dimensions("ollama", "nomic-embed-text")
    assert dims == 768

@pytest.mark.asyncio
async def test_resolve_dimensions_tagged_model_fuzzy_match(service):
    """Test that tagged models match the hardcoded list if base name matches."""
    # Should strip :latest and match nomic-embed-text
    dims = await service._resolve_dimensions("ollama", "nomic-embed-text:latest")
    assert dims == 768

@pytest.mark.asyncio
async def test_resolve_dimensions_unknown_model_dynamic_check(service):
    """Test that unknown models trigger dynamic resolution via EmbeddingService."""
    
    # Mocking ProviderFactory and EmbeddingService flow
    # Since imports are inside the method, we must patch the classes where they are defined
    
    with patch("src.core.providers.factory.ProviderFactory") as MockFactory, \
         patch("src.core.services.embeddings.EmbeddingService") as MockEmbeddingService:
        
        # Setup mock factory to return a provider
        mock_provider = MagicMock()
        mock_factory_instance = MockFactory.return_value
        mock_factory_instance.get_embedding_provider.return_value = mock_provider
        
        # Setup mock embedding service
        mock_service_instance = MockEmbeddingService.return_value
        # Mock embed_texts to return a list of embeddings. 
        # The service calls embed_texts(["test"]), expect list of list of floats
        # Let's say we return 1 embedding of size 123
        mock_service_instance.embed_texts = AsyncMock(return_value=([[0.1] * 123], {}))
        
        dims = await service._resolve_dimensions("ollama", "unknown-custom-model:v1")
        
        assert dims == 123
        # Verify it was called correct
        MockFactory.assert_called()
        MockEmbeddingService.assert_called_with(
            provider=mock_provider,
            model="unknown-custom-model:v1",
            dimensions=1536 # It might initialize with default if not known, but we care about the output
        )
        mock_service_instance.embed_texts.assert_awaited_once()

@pytest.mark.asyncio
async def test_resolve_dimensions_dynamic_failure_defaults(service):
    """Test that if dynamic resolution fails, it falls back to default 1536."""
    
    with patch("src.core.providers.factory.ProviderFactory"), \
         patch("src.core.services.embeddings.EmbeddingService") as MockEmbeddingService:
        
        mock_service_instance = MockEmbeddingService.return_value
        mock_service_instance.embed_texts = AsyncMock(side_effect=Exception("Connection error"))
        
        import logging
        # We expect error log but graceful fallback
        dims = await service._resolve_dimensions("ollama", "super-broken-model")
        
        assert dims == 1536
