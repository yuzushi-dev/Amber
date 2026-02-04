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
from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, EMBEDDING_MODELS


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OLLAMA_DEFAULT = DEFAULT_EMBEDDING_MODEL["ollama"]
OLLAMA_DEFAULT_DIM = EMBEDDING_MODELS["ollama"][OLLAMA_DEFAULT]["dimensions"]
OLLAMA_ALT = _first_other(EMBEDDING_MODELS["ollama"], OLLAMA_DEFAULT)


class TestOllamaEmbeddingProvider:
    """Tests for OllamaEmbeddingProvider."""

    def test_default_configuration(self):
        """Test that default configuration is applied correctly."""
        provider = OllamaEmbeddingProvider()
        
        assert provider.provider_name == "ollama"
        assert provider.default_model == OLLAMA_DEFAULT
        assert OLLAMA_DEFAULT in provider.models
        assert provider.models[OLLAMA_DEFAULT]["dimensions"] == OLLAMA_DEFAULT_DIM

    def test_custom_model_from_env(self, monkeypatch):
        """Test that OLLAMA_EMBEDDING_MODEL env var overrides default."""
        monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", OLLAMA_ALT)
        
        provider = OllamaEmbeddingProvider()
        assert provider.default_model == OLLAMA_ALT

    def test_custom_base_url_from_config(self):
        """Test that base_url can be set via config."""
        config = ProviderConfig(base_url="http://custom:11434/v1")
        provider = OllamaEmbeddingProvider(config)
        
        assert provider.config.base_url == "http://custom:11434/v1"

    def test_supported_models(self):
        """Test that all expected models are registered."""
        provider = OllamaEmbeddingProvider()
        
        expected_models = EMBEDDING_MODELS["ollama"].keys()
        
        for model in expected_models:
            assert model in provider.models

    def test_get_dimensions(self):
        """Test get_dimensions returns correct values for known models."""
        provider = OllamaEmbeddingProvider()

        for model, info in EMBEDDING_MODELS["ollama"].items():
            assert provider.get_dimensions(model) == info["dimensions"]

    @pytest.mark.asyncio
    async def test_embed_success(self):
        """Test successful embedding generation."""
        provider = OllamaEmbeddingProvider()
        
        # Mock the OpenAI client response
        mock_embedding_data = MagicMock()
        mock_embedding_data.index = 0
        mock_embedding_data.embedding = [0.1] * OLLAMA_DEFAULT_DIM
        
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
        assert len(result.embeddings[0]) == OLLAMA_DEFAULT_DIM
        assert result.provider == "ollama"
        assert result.cost_estimate == 0.0  # Local is free

    @pytest.mark.asyncio
    async def test_embed_multiple_texts(self):
        """Test embedding multiple texts."""
        provider = OllamaEmbeddingProvider()
        
        # Mock responses for multiple texts
        mock_data = []
        for i in range(3):
            item = MagicMock()
            item.index = i
            item.embedding = [0.1 * (i + 1)] * OLLAMA_DEFAULT_DIM
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
    async def test_embed_connection_error(self):
        """Test handling of connection errors."""
        provider = OllamaEmbeddingProvider()
        
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
    async def test_embed_preserves_order(self):
        """Test that embeddings are returned in correct order."""
        provider = OllamaEmbeddingProvider()
        
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


class TestOllamaEmbeddingProviderFactory:
    """Test OllamaEmbeddingProvider with ProviderFactory."""

    def test_factory_creates_ollama_embedding_provider(self):
        """Test that factory can create Ollama embedding provider."""
        from src.core.generation.infrastructure.providers.factory import ProviderFactory
        
        factory = ProviderFactory(
            ollama_base_url="http://localhost:11434/v1",
            default_embedding_provider="ollama",
        )
        
        provider = factory.get_embedding_provider()
        
        assert provider.provider_name == "ollama"

    def test_factory_with_custom_model(self):
        """Test factory respects custom embedding model."""
        from src.core.generation.infrastructure.providers.factory import ProviderFactory
        
        factory = ProviderFactory(
            ollama_base_url="http://localhost:11434/v1",
            default_embedding_provider="ollama",
            default_embedding_model="mxbai-embed-large",
        )
        
        provider = factory.get_embedding_provider()
        
        assert provider.default_model == "mxbai-embed-large"
