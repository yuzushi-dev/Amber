"""
Ollama Embedding Provider Tests
===============================

Tests for the OllamaEmbeddingProvider class.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.generation.infrastructure.providers.base import (
    EmbeddingResult,
    ProviderConfig,
    ProviderUnavailableError,
    TokenUsage,
)
from src.core.generation.infrastructure.providers.ollama import OllamaEmbeddingProvider



class TestOllamaEmbeddingProvider:
    """Tests for OllamaEmbeddingProvider."""

    @pytest.fixture
    def test_config(self):
        """Provide a test config with required base_url."""
        return ProviderConfig(base_url="http://test-ollama:11434/v1")

    def test_default_configuration(self, test_config):
        """Test that default configuration is applied correctly."""
        provider = OllamaEmbeddingProvider(test_config)
        
        assert provider.provider_name == "ollama"
        assert provider.default_model == "nomic-embed-text"
        assert "nomic-embed-text" in provider.models
        assert provider.models["nomic-embed-text"]["dimensions"] == 768

    def test_custom_model_from_env(self, monkeypatch, test_config):
        """Test that OLLAMA_EMBEDDING_MODEL env var overrides default."""
        monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")
        
        provider = OllamaEmbeddingProvider(test_config)
        assert provider.default_model == "mxbai-embed-large"

    def test_custom_base_url_from_config(self):
        """Test that base_url can be set via config."""
        config = ProviderConfig(base_url="http://custom:11434/v1")
        provider = OllamaEmbeddingProvider(config)
        
        assert provider.config.base_url == "http://custom:11434/v1"

    def test_supported_models(self, test_config):
        """Test that all expected models are registered."""
        provider = OllamaEmbeddingProvider(test_config)
        
        expected_models = [
            "nomic-embed-text",
            "mxbai-embed-large", 
            "all-minilm",
            "snowflake-arctic-embed",
        ]
        
        for model in expected_models:
            assert model in provider.models

    def test_get_dimensions(self, test_config):
        """Test get_dimensions returns correct values for known models."""
        provider = OllamaEmbeddingProvider(test_config)
        
        assert provider.get_dimensions("nomic-embed-text") == 768
        assert provider.get_dimensions("mxbai-embed-large") == 1024
        assert provider.get_dimensions("all-minilm") == 384

    @pytest.mark.asyncio
    async def test_embed_success(self, test_config):
        """Test successful embedding generation."""
        provider = OllamaEmbeddingProvider(test_config)
        
        # Mock the OpenAI client response
        mock_embedding_data = MagicMock()
        mock_embedding_data.index = 0
        mock_embedding_data.embedding = [0.1] * 768
        
        mock_response = MagicMock()
        mock_response.data = [mock_embedding_data]
        mock_response.usage = MagicMock()
        mock_response.usage.total_tokens = 10
        
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client
        
        result = await provider.embed(["Hello, world!"])
        
        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 1
        assert len(result.embeddings[0]) == 768
        assert result.provider == "ollama"
        assert result.cost_estimate == 0.0  # Local is free

    @pytest.mark.asyncio
    async def test_embed_multiple_texts(self, test_config):
        """Test embedding multiple texts."""
        provider = OllamaEmbeddingProvider(test_config)
        
        # Mock responses for multiple texts
        mock_data = []
        for i in range(3):
            item = MagicMock()
            item.index = i
            item.embedding = [0.1 * (i + 1)] * 768
            mock_data.append(item)
        
        mock_response = MagicMock()
        mock_response.data = mock_data
        mock_response.usage = MagicMock()
        mock_response.usage.total_tokens = 30
        
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client
        
        result = await provider.embed(["Text 1", "Text 2", "Text 3"])
        
        assert len(result.embeddings) == 3
        assert result.usage.input_tokens == 30

    @pytest.mark.asyncio
    async def test_embed_connection_error(self, test_config):
        """Test handling of connection errors."""
        provider = OllamaEmbeddingProvider(test_config)
        
        mock_client = AsyncMock()
        # Simulate connection error
        from openai import APIConnectionError
        mock_client.embeddings.create = AsyncMock(
            side_effect=APIConnectionError(request=MagicMock())
        )
        provider._client = mock_client
        
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await provider.embed(["Hello"])
        
        assert "Cannot connect to Ollama" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_embed_preserves_order(self, test_config):
        """Test that embeddings are returned in correct order."""
        provider = OllamaEmbeddingProvider(test_config)
        
        # Mock responses returned in reverse order
        mock_data = []
        for i in [2, 0, 1]:  # Out of order
            item = MagicMock()
            item.index = i
            item.embedding = [float(i)] * 768
            mock_data.append(item)
        
        mock_response = MagicMock()
        mock_response.data = mock_data
        mock_response.usage = MagicMock()
        mock_response.usage.total_tokens = 30
        
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client
        
        result = await provider.embed(["A", "B", "C"])
        
        # Should be sorted by index
        assert result.embeddings[0][0] == 0.0
        assert result.embeddings[1][0] == 1.0
        assert result.embeddings[2][0] == 2.0


# Test fixture URL for Ollama tests
TEST_OLLAMA_BASE_URL = "http://test-ollama:11434/v1"


class TestOllamaEmbeddingProviderFactory:
    """Test OllamaEmbeddingProvider with ProviderFactory."""

    def test_factory_creates_ollama_embedding_provider(self):
        """Test that factory can create Ollama embedding provider."""
        from src.core.generation.infrastructure.providers.factory import ProviderFactory
        
        factory = ProviderFactory(
            ollama_base_url=TEST_OLLAMA_BASE_URL,
            default_embedding_provider="ollama",
        )
        
        provider = factory.get_embedding_provider()
        
        assert provider.provider_name == "ollama"

    def test_factory_with_custom_model(self):
        """Test factory respects custom embedding model."""
        from src.core.generation.infrastructure.providers.factory import ProviderFactory
        
        factory = ProviderFactory(
            ollama_base_url=TEST_OLLAMA_BASE_URL,
            default_embedding_provider="ollama",
            default_embedding_model="mxbai-embed-large",
        )
        
        provider = factory.get_embedding_provider()
        
        assert provider.default_model == "mxbai-embed-large"
