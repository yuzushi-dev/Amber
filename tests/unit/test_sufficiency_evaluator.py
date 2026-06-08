"""
Unit tests for SufficiencyEvaluator (iterative-retrieval sufficiency gate).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application.query.sufficiency import (
    SufficiencyEvaluator,
    SufficiencyVerdict,
)


def _evaluator_with_response(text: str) -> tuple[SufficiencyEvaluator, AsyncMock]:
    """Build an evaluator whose LLM returns `text`, and return (evaluator, provider)."""
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = SimpleNamespace(text=text)
    mock_factory = MagicMock()
    mock_factory.get_llm_provider.return_value = mock_provider

    evaluator = SufficiencyEvaluator(provider=mock_provider, provider_factory=mock_factory)
    return evaluator, mock_provider


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


@pytest.mark.asyncio
async def test_empty_chunks_is_insufficient_without_llm():
    evaluator, provider = _evaluator_with_response("{}")
    verdict = await evaluator.evaluate("What is X?", chunks=[])

    assert verdict.is_sufficient is False
    assert verdict.gap_queries == ["What is X?"]
    # No LLM call needed when there is nothing to judge.
    provider.generate.assert_not_called()


@pytest.mark.asyncio
async def test_sufficient_verdict_parsed():
    evaluator, _ = _evaluator_with_response(
        '{"sufficient": true, "reason": "all covered", "gap_queries": []}'
    )
    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate("q", chunks=[{"content": "answer here"}])

    assert verdict.is_sufficient is True
    assert verdict.gap_queries == []


@pytest.mark.asyncio
async def test_insufficient_with_gap_queries():
    evaluator, _ = _evaluator_with_response(
        '{"sufficient": false, "reason": "missing allergies", '
        '"gap_queries": ["allergy info", "adverse events"]}'
    )
    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate("meds?", chunks=[{"content": "meds and diet"}])

    assert verdict.is_sufficient is False
    assert verdict.gap_queries == ["allergy info", "adverse events"]


@pytest.mark.asyncio
async def test_gap_queries_capped_at_max():
    evaluator, _ = _evaluator_with_response(
        '{"sufficient": false, "reason": "x", "gap_queries": ["a", "b", "c", "d", "e"]}'
    )
    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate(
            "q", chunks=[{"content": "c"}], max_gap_queries=2
        )

    assert len(verdict.gap_queries) == 2


@pytest.mark.asyncio
async def test_insufficient_but_no_gaps_treated_as_sufficient():
    # Avoid a wasted retrieval round when the model gives no actionable gaps.
    evaluator, _ = _evaluator_with_response(
        '{"sufficient": false, "reason": "vague", "gap_queries": []}'
    )
    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate("q", chunks=[{"content": "c"}])

    assert verdict.is_sufficient is True


@pytest.mark.asyncio
async def test_unparseable_response_fails_open():
    evaluator, _ = _evaluator_with_response("not json at all, sorry")
    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate("q", chunks=[{"content": "c"}])

    assert verdict.is_sufficient is True


@pytest.mark.asyncio
async def test_json_embedded_in_prose_is_extracted():
    evaluator, _ = _evaluator_with_response(
        'Here is my verdict: {"sufficient": false, "reason": "r", '
        '"gap_queries": ["g1"]} — hope that helps!'
    )
    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate("q", chunks=[{"content": "c"}])

    assert verdict.is_sufficient is False
    assert verdict.gap_queries == ["g1"]


@pytest.mark.asyncio
async def test_fenced_json_block_is_parsed():
    evaluator, _ = _evaluator_with_response(
        '```json\n{"sufficient": true, "reason": "ok", "gap_queries": []}\n```'
    )
    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate("q", chunks=[{"content": "c"}])

    assert verdict.is_sufficient is True


@pytest.mark.asyncio
async def test_llm_exception_fails_open():
    mock_provider = AsyncMock()
    mock_provider.generate.side_effect = RuntimeError("provider down")
    mock_factory = MagicMock()
    mock_factory.get_llm_provider.return_value = mock_provider
    evaluator = SufficiencyEvaluator(provider=mock_provider, provider_factory=mock_factory)

    p1, p2 = _patches()
    with p1, p2:
        verdict = await evaluator.evaluate("q", chunks=[{"content": "c"}])

    assert verdict.is_sufficient is True
    assert verdict.reason == "evaluation_error"


@pytest.mark.asyncio
async def test_tried_gap_queries_injected_into_prompt():
    evaluator, provider = _evaluator_with_response(
        '{"sufficient": false, "reason": "r", "gap_queries": ["new angle"]}'
    )
    p1, p2 = _patches()
    with p1, p2:
        await evaluator.evaluate(
            "q", chunks=[{"content": "c"}],
            tried_gap_queries=["old gap one", "old gap two"],
        )
    prompt = provider.generate.await_args.args[0]
    assert "ALREADY attempted" in prompt
    assert "old gap one" in prompt and "old gap two" in prompt


@pytest.mark.asyncio
async def test_draft_answer_injected_into_prompt():
    evaluator, provider = _evaluator_with_response(
        '{"sufficient": true, "reason": "ok", "gap_queries": []}'
    )
    p1, p2 = _patches()
    with p1, p2:
        await evaluator.evaluate(
            "q", chunks=[{"content": "c"}],
            draft_answer="This is a partial draft answer.",
        )
    prompt = provider.generate.await_args.args[0]
    assert "Draft answer under review" in prompt
    assert "This is a partial draft answer." in prompt


@pytest.mark.asyncio
async def test_no_optional_blocks_when_absent():
    evaluator, provider = _evaluator_with_response(
        '{"sufficient": true, "reason": "ok", "gap_queries": []}'
    )
    p1, p2 = _patches()
    with p1, p2:
        await evaluator.evaluate("q", chunks=[{"content": "c"}])
    prompt = provider.generate.await_args.args[0]
    assert "ALREADY attempted" not in prompt
    assert "Draft answer under review" not in prompt


def test_verdict_dataclass_defaults():
    v = SufficiencyVerdict(is_sufficient=True)
    assert v.reason == ""
    assert v.gap_queries == []
