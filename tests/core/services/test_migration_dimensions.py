from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.admin_ops.application.migration_service import EmbeddingMigrationService
from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, EMBEDDING_MODELS

OPENAI_EMBEDDING = DEFAULT_EMBEDDING_MODEL["openai"]
OPENAI_EMBEDDING_DIM = EMBEDDING_MODELS["openai"][OPENAI_EMBEDDING]["dimensions"]
OLLAMA_EMBEDDING = DEFAULT_EMBEDDING_MODEL["ollama"]
OLLAMA_EMBEDDING_DIM = EMBEDDING_MODELS["ollama"][OLLAMA_EMBEDDING]["dimensions"]


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.openai_api_key = None
    settings.ollama_base_url = None
    return settings


@pytest.fixture
def mock_task_dispatcher():
    return AsyncMock()


@pytest.fixture
def mock_graph_client():
    return AsyncMock()


@pytest.fixture
def mock_vector_store_factory():
    return MagicMock()


@pytest.fixture
def service(
    mock_session,
    mock_settings,
    mock_task_dispatcher,
    mock_graph_client,
    mock_vector_store_factory,
):
    return EmbeddingMigrationService(
        mock_session,
        mock_settings,
        mock_task_dispatcher,
        mock_graph_client,
        mock_vector_store_factory,
    )


@pytest.mark.asyncio
async def test_resolve_dimensions_known_model(service):
    """Test that known registry models return correct dimensions without calling provider."""
    dims = await service._resolve_dimensions("openai", OPENAI_EMBEDDING)
    assert dims == OPENAI_EMBEDDING_DIM

    dims = await service._resolve_dimensions("ollama", OLLAMA_EMBEDDING)
    assert dims == OLLAMA_EMBEDDING_DIM


@pytest.mark.asyncio
async def test_resolve_dimensions_tagged_model_fuzzy_match(service):
    """Test that tagged models match the registry list if base name matches."""
    dims = await service._resolve_dimensions("ollama", f"{OLLAMA_EMBEDDING}:latest")
    assert dims == OLLAMA_EMBEDDING_DIM


@pytest.mark.asyncio
async def test_resolve_dimensions_unknown_model_dynamic_check(service):
    """Test that unknown models trigger dynamic resolution via EmbeddingService."""

    # Mocking ProviderFactory and EmbeddingService flow
    # Since imports are inside the method, we must patch the classes where they are defined

    with (
        patch(
            "src.core.generation.domain.ports.provider_factory.build_provider_factory"
        ) as MockFactory,
        patch(
            "src.core.retrieval.application.embeddings_service.EmbeddingService"
        ) as MockEmbeddingService,
    ):
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
            dimensions=OPENAI_EMBEDDING_DIM,  # It might initialize with default if not known, but we care about the output
        )
        mock_service_instance.embed_texts.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_dimensions_dynamic_failure_defaults(service):
    """Test that if dynamic resolution fails, it falls back to default 1536."""

    with (
        patch("src.core.generation.domain.ports.provider_factory.build_provider_factory"),
        patch(
            "src.core.retrieval.application.embeddings_service.EmbeddingService"
        ) as MockEmbeddingService,
    ):
        mock_service_instance = MockEmbeddingService.return_value
        mock_service_instance.embed_texts = AsyncMock(side_effect=Exception("Connection error"))

        # We expect error log but graceful fallback
        dims = await service._resolve_dimensions("ollama", "super-broken-model")

        assert dims == OPENAI_EMBEDDING_DIM
