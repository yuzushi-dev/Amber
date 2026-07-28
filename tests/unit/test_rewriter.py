"""
Unit tests for QueryRewriter (asyncio.wait_for timeout guard + output sanity guard).
"""

import asyncio
import time
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


def _rewriter_with_delay_tracking(text: str, delay: float):
    """Like _rewriter_with_delay, but also exposes a dict tracking whether the
    fake generate() call ever ran to completion. asyncio.wait_for cancels the
    awaited coroutine on timeout, so a real cutoff must leave completed=False;
    a post-hoc "await fully, then check elapsed" implementation would let it
    finish and leave completed=True."""
    mock_provider = MagicMock()
    state = {"completed": False}

    async def _generate(*args, **kwargs):
        await asyncio.sleep(delay)
        state["completed"] = True
        return SimpleNamespace(text=text)

    mock_provider.generate = _generate
    mock_factory = MagicMock()
    mock_factory.get_llm_provider.return_value = mock_provider
    return QueryRewriter(provider=mock_provider, provider_factory=mock_factory), state


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
    """asyncio.wait_for must actually cancel a slow LLM call, not just await it
    fully and discard the result afterward. Both assertions are needed to
    discriminate a real cutoff from a post-hoc elapsed-time check: the old
    post-hoc code returns the same "original query" value, just ~1s later,
    with generate() having run to completion."""
    timeout_sec = 0.05
    rewriter, state = _rewriter_with_delay_tracking("standalone rewritten query", delay=1.0)
    p1, p2 = _patches()
    start = time.perf_counter()
    with p1, p2:
        result = await rewriter.rewrite("original query", history=HISTORY, timeout_sec=timeout_sec)
    elapsed = time.perf_counter() - start

    assert result == "original query"
    # Real cutoff: returns well before the 1.0s delay, not after waiting it out.
    assert elapsed < timeout_sec * 5, f"took {elapsed:.2f}s, expected a cutoff near {timeout_sec}s"
    # The awaited generate() coroutine must have been cancelled, not left to
    # run to completion in the background.
    assert state["completed"] is False


@pytest.mark.asyncio
async def test_empty_output_returns_original_query(caplog):
    """A blank/whitespace-only rewrite must not replace the original query -
    and must be caught by the empty-output guard specifically (not by the
    generic exception fallback, which would also return the original query
    even if _patches() silently failed to patch anything)."""
    rewriter = _rewriter_with_response("   ")
    p1, p2 = _patches()
    with p1, p2, caplog.at_level("WARNING"):
        result = await rewriter.rewrite("original query", history=HISTORY)

    assert result == "original query"
    assert any("empty output" in r.message for r in caplog.records)
    assert not any("Query rewrite failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_disproportionate_output_returns_original_query(caplog):
    """An absurdly long rewrite relative to the input query is rejected as a
    guard failure specifically (not via the generic exception fallback)."""
    rewriter = _rewriter_with_response("x" * 1000)
    p1, p2 = _patches()
    with p1, p2, caplog.at_level("WARNING"):
        result = await rewriter.rewrite("hi", history=HISTORY)

    assert result == "hi"
    assert any("disproportionate" in r.message for r in caplog.records)
    assert not any("Query rewrite failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_short_followup_gets_plausible_standalone_rewrite_kept():
    """A short follow-up ("spiega meglio?", 14 chars) legitimately rewrites
    to something much longer once it's made standalone with context folded
    in (~250 chars here) — the disproportionate-output guard must not reject
    this, or it defeats the very case multi-turn rewriting exists for."""
    short_query = "spiega meglio?"  # 14 chars
    plausible_rewrite = (
        "Puoi spiegare meglio le limitazioni del piano UMR (User Mail Replica) "
        "per quanto riguarda la sincronizzazione degli allegati di grandi "
        "dimensioni tra i server primario e secondario?"
    )  # ~250 chars, a believable standalone expansion of the short follow-up
    assert len(plausible_rewrite) > 4 * len(short_query)  # would fail the old floor

    rewriter = _rewriter_with_response(plausible_rewrite)
    p1, p2 = _patches()
    with p1, p2:
        result = await rewriter.rewrite(short_query, history=HISTORY)

    assert result == plausible_rewrite


@pytest.mark.asyncio
async def test_valid_output_is_returned_rewritten():
    """A well-behaved rewrite within timeout and size bounds is returned as-is."""
    rewriter = _rewriter_with_response("standalone rewritten query")
    p1, p2 = _patches()
    with p1, p2:
        result = await rewriter.rewrite("original query", history=HISTORY)

    assert result == "standalone rewritten query"
