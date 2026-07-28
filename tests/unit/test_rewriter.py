"""
Unit tests for QueryRewriter (asyncio.wait_for timeout guard + output sanity guard).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.retrieval.application.query.rewriter import QueryRewriter


def _rewriter_with_response(text: str) -> QueryRewriter:
    """Build a QueryRewriter whose LLM call returns `text`."""
    mock_provider = MagicMock()

    async def _generate(*args, **kwargs):
        return SimpleNamespace(text=text)

    mock_provider.generate = _generate
    mock_factory = MagicMock()
    mock_factory.get_llm_provider.return_value = mock_provider
    return QueryRewriter(provider=mock_provider, provider_factory=mock_factory)


def _rewriter_with_delay(text: str, delay: float) -> QueryRewriter:
    """Build a QueryRewriter whose LLM call sleeps `delay` seconds before returning `text`."""
    mock_provider = MagicMock()

    async def _generate(*args, **kwargs):
        await asyncio.sleep(delay)
        return SimpleNamespace(text=text)

    mock_provider.generate = _generate
    mock_factory = MagicMock()
    mock_factory.get_llm_provider.return_value = mock_provider
    return QueryRewriter(provider=mock_provider, provider_factory=mock_factory)


def _patches():
    mock_cfg = MagicMock()
    mock_cfg.provider = "openai"
    mock_cfg.model = "gpt-test"
    mock_cfg.temperature = 0.0
    mock_cfg.seed = 42
    return (
        patch("src.shared.kernel.runtime.get_settings"),
        patch(
            "src.core.generation.application.llm_steps.resolve_llm_step_config",
            return_value=mock_cfg,
        ),
    )


HISTORY = [{"role": "user", "content": "previous turn"}]


@pytest.mark.asyncio
async def test_no_history_or_context_short_circuits_without_llm_call():
    """With nothing to rewrite from, the rewriter must not touch the LLM at all."""
    mock_provider = MagicMock()
    mock_provider.generate = MagicMock(side_effect=AssertionError("should not be called"))
    mock_factory = MagicMock()
    mock_factory.get_llm_provider.return_value = mock_provider
    rewriter = QueryRewriter(provider=mock_provider, provider_factory=mock_factory)

    result = await rewriter.rewrite("plain query")

    assert result == "plain query"


@pytest.mark.asyncio
async def test_timeout_returns_original_query():
    """asyncio.wait_for must cut off a slow LLM call and fall back to the original query."""
    rewriter = _rewriter_with_delay("standalone rewritten query", delay=1.0)
    p1, p2 = _patches()
    with p1, p2:
        result = await rewriter.rewrite("original query", history=HISTORY, timeout_sec=0.05)

    assert result == "original query"


@pytest.mark.asyncio
async def test_empty_output_returns_original_query():
    """A blank/whitespace-only rewrite must not replace the original query."""
    rewriter = _rewriter_with_response("   ")
    p1, p2 = _patches()
    with p1, p2:
        result = await rewriter.rewrite("original query", history=HISTORY)

    assert result == "original query"


@pytest.mark.asyncio
async def test_disproportionate_output_returns_original_query():
    """An absurdly long rewrite relative to the input query is rejected as a guard failure."""
    rewriter = _rewriter_with_response("x" * 1000)
    p1, p2 = _patches()
    with p1, p2:
        result = await rewriter.rewrite("hi", history=HISTORY)

    assert result == "hi"


@pytest.mark.asyncio
async def test_valid_output_is_returned_rewritten():
    """A well-behaved rewrite within timeout and size bounds is returned as-is."""
    rewriter = _rewriter_with_response("standalone rewritten query")
    p1, p2 = _patches()
    with p1, p2:
        result = await rewriter.rewrite("original query", history=HISTORY)

    assert result == "standalone rewritten query"
