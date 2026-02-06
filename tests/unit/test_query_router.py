"""
Unit tests for QueryRouter
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.retrieval.application.query.router import QueryRouter
from src.shared.kernel.models.query import SearchMode
from src.shared.model_registry import DEFAULT_LLM_MODEL


@pytest.mark.asyncio
async def test_router_heuristics_global():
    router = QueryRouter(provider=AsyncMock(), provider_factory=MagicMock())

    # "summarize" should trigger GLOBAL
    mode = await router.route("Summarize the project status")
    assert mode == SearchMode.GLOBAL


@pytest.mark.asyncio
async def test_router_heuristics_drift():
    router = QueryRouter(provider=AsyncMock(), provider_factory=MagicMock())

    # "compare" should trigger DRIFT
    mode = await router.route("Compare the two reports")
    assert mode == SearchMode.DRIFT


@pytest.mark.asyncio
async def test_router_llm_classification():
    from unittest.mock import MagicMock, patch

    # Setup mocks
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = "local"

    # Provider factory is synchronous
    mock_factory = MagicMock()
    mock_factory.get_llm_provider.return_value = mock_provider

    mock_llm_config = MagicMock()
    mock_llm_config.provider = "openai"
    mock_llm_config.model = DEFAULT_LLM_MODEL["openai"]
    mock_llm_config.temperature = 0.0
    mock_llm_config.seed = 42

    # Patch dependencies used inside the method
    with (
        patch("src.shared.kernel.runtime.get_settings"),
        patch(
            "src.core.generation.application.llm_steps.resolve_llm_step_config",
            return_value=mock_llm_config,
        ),
    ):
        router = QueryRouter(provider=mock_provider, provider_factory=mock_factory)

        # No keywords, should hit LLM
        mode = await router.route("Who is the CEO of Microsoft?", use_llm=True)

        assert mode == SearchMode.LOCAL
        # Verify the factory was used to get the provider
        mock_factory.get_llm_provider.assert_called_once()
        # Verify the provider generated the response
        mock_provider.generate.assert_called_once()


@pytest.mark.asyncio
async def test_router_explicit_override():
    router = QueryRouter(provider=AsyncMock(), provider_factory=MagicMock())

    mode = await router.route("Summarize", explicit_mode=SearchMode.BASIC)
    assert mode == SearchMode.BASIC
