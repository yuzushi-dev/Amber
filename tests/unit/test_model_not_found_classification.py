"""
Unit tests for Issue #28.3: Classify "model not found" as permanent InvalidRequestError.

#28.3: Model-not-found errors (e.g. model 'gemma:invalid' not found / NotFoundError / does not exist)
must raise InvalidRequestError rather than ProviderUnavailableError. ProviderUnavailableError
is treated as transient by circuit breakers and failover, whereas model-not-found is a permanent
configuration error and must fail fast without tripping circuit breakers.
"""

import pytest

from src.api.config import settings as api_settings
from src.core.generation.domain.provider_models import InvalidRequestError, ProviderConfig
from src.core.generation.infrastructure.providers.ollama import OllamaEmbeddingProvider, OllamaLLMProvider
from src.core.generation.infrastructure.providers.openai import OpenAILLMProvider
from src.shared.kernel.runtime import configure_settings


@pytest.fixture(autouse=True)
def setup_settings():
    configure_settings(api_settings)


class FakeNotFoundError(Exception):
    """Simulates an SDK NotFoundError (e.g. httpx / openai / ollama API error)."""
    pass


class FakeModelNotFoundException(Exception):
    """Simulates a generic exception carrying 'model not found' in message."""
    pass


def test_ollama_llm_provider_model_not_found_raises_invalid_request_error():
    provider = OllamaLLMProvider(
        config=ProviderConfig(base_url="http://localhost:11434"),
        use_capacity_limiter=False,
    )

    err = FakeModelNotFoundException("model 'nonexistent-model:latest' not found")
    with pytest.raises(InvalidRequestError) as exc_info:
        provider._handle_error(err, model="nonexistent-model:latest")

    assert exc_info.value.model == "nonexistent-model:latest"
    assert "not found" in str(exc_info.value).lower()


def test_ollama_llm_provider_not_found_error_type_raises_invalid_request_error():
    provider = OllamaLLMProvider(
        config=ProviderConfig(base_url="http://localhost:11434"),
        use_capacity_limiter=False,
    )

    err = FakeNotFoundError("The requested resource was not found")
    with pytest.raises(InvalidRequestError) as exc_info:
        provider._handle_error(err, model="missing-model")

    assert exc_info.value.model == "missing-model"


def test_ollama_embedding_provider_model_not_found_raises_invalid_request_error():
    provider = OllamaEmbeddingProvider(
        config=ProviderConfig(base_url="http://localhost:11434"),
    )

    err = FakeModelNotFoundException("model 'nomic-embed-text:missing' not found")
    with pytest.raises(InvalidRequestError) as exc_info:
        provider._handle_error(err, model="nomic-embed-text:missing")

    assert exc_info.value.model == "nomic-embed-text:missing"


def test_openai_llm_provider_model_not_found_raises_invalid_request_error():
    provider = OpenAILLMProvider(config=ProviderConfig(api_key="test-key"))

    err = FakeModelNotFoundException("The model `gpt-nonexistent` does not exist")
    with pytest.raises(InvalidRequestError) as exc_info:
        provider._handle_error(err, model="gpt-nonexistent")

    assert exc_info.value.model == "gpt-nonexistent"
