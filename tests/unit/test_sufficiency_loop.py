"""
Integration tests for RetrievalService._run_sufficiency_loop.

Exercises the iterative-retrieval wiring (merge/dedup, score-sort, top_k cap,
round limits, stop conditions, fail-safe) without a DB/LLM by injecting a
mocked sufficiency evaluator and a mocked _execute_vector_search onto a bare
RetrievalService instance.
"""

from unittest.mock import AsyncMock

import pytest

from src.core.retrieval.application.retrieval_service import (
    RetrievalResult,
    RetrievalService,
    VectorSearchTarget,
)
from src.core.retrieval.application.query.sufficiency import SufficiencyVerdict
from src.shared.kernel.models.query import QueryOptions


def _chunk(cid: str, score: float, content: str = "x") -> dict:
    return {"chunk_id": cid, "document_id": "d", "score": score, "content": content}


def _bare_service() -> RetrievalService:
    """A RetrievalService with __init__ bypassed; only loop deps are set."""
    return RetrievalService.__new__(RetrievalService)


def _result(chunks: list[dict]) -> RetrievalResult:
    return RetrievalResult(chunks=list(chunks), query="q", tenant_id="t", latency_ms=0.0)


async def _run(
    svc: RetrievalService,
    result: RetrievalResult,
    *,
    max_rounds: int = 2,
    top_k: int = 10,
    include_trace: bool = True,
) -> list[dict]:
    trace: list[dict] = []
    options = QueryOptions(
        use_sufficiency_loop=True, max_sufficiency_rounds=max_rounds
    )
    await svc._run_sufficiency_loop(
        result=result,
        processed_query="original query",
        tenant_id="t",
        document_ids=None,
        filters={},
        top_k=top_k,
        options=options,
        trace=trace,
        vector_targets=[VectorSearchTarget(tenant_id="t", collection_name="c")],
        tenant_config=None,
        include_trace=include_trace,
    )
    return trace


@pytest.mark.asyncio
async def test_sufficient_first_round_no_extra_retrieval():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=True, reason="ok"
    )
    svc._execute_vector_search = AsyncMock()

    result = _result([_chunk("a", 0.9)])
    trace = await _run(svc, result)

    svc._execute_vector_search.assert_not_called()
    assert [c["chunk_id"] for c in result.chunks] == ["a"]
    assert len(trace) == 1
    assert trace[0]["sufficient"] is True


@pytest.mark.asyncio
async def test_insufficient_then_gap_merged_then_stops():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, reason="gap", gap_queries=["g1"]),
        SufficiencyVerdict(is_sufficient=True, reason="now ok"),
    ]
    # Gap query returns a new, higher-scoring chunk.
    svc._execute_vector_search = AsyncMock(
        return_value=_result([_chunk("b", 0.95, "gap content")])
    )

    result = _result([_chunk("a", 0.5)])
    trace = await _run(svc, result)

    assert svc._execute_vector_search.await_count == 1
    # b merged and sorted above a.
    assert [c["chunk_id"] for c in result.chunks] == ["b", "a"]
    # Evaluated twice (insufficient -> sufficient).
    assert svc.sufficiency_evaluator.evaluate.await_count == 2
    assert len(trace) == 2


@pytest.mark.asyncio
async def test_dedup_no_new_chunks_breaks_early():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    # Always insufficient, but gap returns a chunk already present.
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False, reason="gap", gap_queries=["g1"]
    )
    svc._execute_vector_search = AsyncMock(return_value=_result([_chunk("a", 0.9)]))

    result = _result([_chunk("a", 0.9)])
    await _run(svc, result, max_rounds=3)

    # Round 1 retrieves, adds nothing new -> breaks; only 1 evaluate, 1 search.
    assert svc.sufficiency_evaluator.evaluate.await_count == 1
    assert svc._execute_vector_search.await_count == 1
    assert [c["chunk_id"] for c in result.chunks] == ["a"]


@pytest.mark.asyncio
async def test_max_rounds_respected_when_always_insufficient():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    # Distinct gap queries each round so anti-repetition does not short-circuit.
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, reason="gap", gap_queries=["g1"]),
        SufficiencyVerdict(is_sufficient=False, reason="gap", gap_queries=["g2"]),
    ]
    # Each round surfaces a fresh chunk so the loop never breaks on "added==0".
    counter = {"n": 0}

    async def _fresh(*_args, **_kwargs):
        counter["n"] += 1
        return _result([_chunk(f"new{counter['n']}", 0.99)])

    svc._execute_vector_search = AsyncMock(side_effect=_fresh)

    result = _result([_chunk("a", 0.5)])
    await _run(svc, result, max_rounds=2, top_k=50)

    assert svc.sufficiency_evaluator.evaluate.await_count == 2
    assert svc._execute_vector_search.await_count == 2


@pytest.mark.asyncio
async def test_repeated_gap_queries_stop_early():
    # Judge keeps proposing the SAME gap query -> anti-repetition stops after
    # round 1 (no fresh gap in round 2).
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False, reason="gap", gap_queries=["same gap"]
    )
    svc._execute_vector_search = AsyncMock(
        return_value=_result([_chunk("b", 0.95)])
    )

    result = _result([_chunk("a", 0.5)])
    await _run(svc, result, max_rounds=3)

    # Round 1 tries "same gap"; round 2 sees it already tried -> breaks.
    assert svc.sufficiency_evaluator.evaluate.await_count == 2
    assert svc._execute_vector_search.await_count == 1


@pytest.mark.asyncio
async def test_tried_gap_queries_passed_to_evaluator():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, reason="gap", gap_queries=["alpha"]),
        SufficiencyVerdict(is_sufficient=True, reason="ok"),
    ]
    svc._execute_vector_search = AsyncMock(return_value=_result([_chunk("b", 0.9)]))

    result = _result([_chunk("a", 0.5)])
    await _run(svc, result, max_rounds=2)

    # Second evaluate call must receive the previously-tried gap "alpha".
    second_call = svc.sufficiency_evaluator.evaluate.await_args_list[1]
    assert second_call.kwargs.get("tried_gap_queries") == ["alpha"]


@pytest.mark.asyncio
async def test_gap_chunks_expand_context_beyond_top_k():
    # The loop ADDS gap chunks (budget = top_k + rounds*3) instead of capping
    # back to top_k, so narrow gap chunks do not evict the original best chunks.
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, reason="gap", gap_queries=["g"]),
        SufficiencyVerdict(is_sufficient=True),
    ]
    svc._execute_vector_search = AsyncMock(
        return_value=_result([_chunk("b", 0.8), _chunk("c", 0.7)])
    )

    result = _result([_chunk("a", 0.9)])
    await _run(svc, result, top_k=2, max_rounds=2)

    # budget = 2 + 2*3 = 8 -> all three kept, original "a" retained.
    assert [c["chunk_id"] for c in result.chunks] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_sufficiency_max_chunks_caps_budget():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, reason="gap", gap_queries=["g"]),
        SufficiencyVerdict(is_sufficient=True),
    ]
    svc._execute_vector_search = AsyncMock(
        return_value=_result([_chunk("b", 0.8), _chunk("c", 0.7)])
    )
    result = _result([_chunk("a", 0.9)])
    trace: list[dict] = []
    opts = QueryOptions(
        use_sufficiency_loop=True, max_sufficiency_rounds=2, sufficiency_max_chunks=2
    )
    await svc._run_sufficiency_loop(
        result=result, processed_query="q", tenant_id="t", document_ids=None,
        filters={}, top_k=2, options=opts, trace=trace,
        vector_targets=[VectorSearchTarget(tenant_id="t", collection_name="c")],
        tenant_config=None, include_trace=False,
    )
    # explicit budget=2 -> capped, only the two top-scoring kept.
    assert [c["chunk_id"] for c in result.chunks] == ["a", "b"]


@pytest.mark.asyncio
async def test_gap_retrieval_exception_is_swallowed():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, reason="gap", gap_queries=["g1", "g2"]),
        SufficiencyVerdict(is_sufficient=True),
    ]

    async def _maybe_fail(*_args, structured_query=None, **_kwargs):
        if structured_query.cleaned_query == "g1":
            raise RuntimeError("milvus down")
        return _result([_chunk("b", 0.95)])

    svc._execute_vector_search = AsyncMock(side_effect=_maybe_fail)

    result = _result([_chunk("a", 0.5)])
    await _run(svc, result)

    # g1 failed, g2 succeeded -> b merged, no crash.
    assert "b" in [c["chunk_id"] for c in result.chunks]


@pytest.mark.asyncio
async def test_no_trace_when_include_trace_false():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=True
    )
    svc._execute_vector_search = AsyncMock()

    result = _result([_chunk("a", 0.9)])
    trace = await _run(svc, result, include_trace=False)

    assert trace == []
