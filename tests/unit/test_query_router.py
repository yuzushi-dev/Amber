"""
Unit tests for QueryRouter
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.query.router import QueryRouter
from src.api.schemas.query import SearchMode


@pytest.mark.asyncio
async def test_router_heuristics_global():
    router = QueryRouter(provider=AsyncMock())
    
    # "summarize" should trigger GLOBAL
    mode = await router.route("Summarize the project status")
    assert mode == SearchMode.GLOBAL


@pytest.mark.asyncio
async def test_router_heuristics_drift():
    router = QueryRouter(provider=AsyncMock())
    
    # "compare" should trigger DRIFT
    mode = await router.route("Compare the two reports")
    assert mode == SearchMode.DRIFT


@pytest.mark.asyncio
async def test_router_llm_classification():
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = "local"
    router = QueryRouter(provider=mock_provider)
    
    # No keywords, should hit LLM
    mode = await router.route("Who is the CEO of Microsoft?", use_llm=True)
    assert mode == SearchMode.LOCAL
    mock_provider.generate.assert_called_once()


@pytest.mark.asyncio
async def test_router_explicit_override():
    router = QueryRouter(provider=AsyncMock())
    
    mode = await router.route("Summarize", explicit_mode=SearchMode.BASIC)
    assert mode == SearchMode.BASIC
