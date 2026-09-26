"""
Integration tests for RetrievalService._run_sufficiency_loop.

Exercises the iterative-retrieval wiring (merge/dedup, score-sort, top_k cap,
round limits, stop conditions, fail-safe) without a DB/LLM by injecting a
mocked sufficiency evaluator and a mocked _execute_vector_search onto a bare
RetrievalService instance.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.retrieval.application.query.sufficiency import SufficiencyVerdict
from src.core.retrieval.application.retrieval_service import (
    RetrievalResult,
    RetrievalService,
    VectorSearchTarget,
    _validated_rerank_results,
)
from src.shared.kernel.models.query import QueryOptions


def _chunk(cid: str, score: float, content: str | None = None) -> dict:
    return {
        "chunk_id": cid,
        "document_id": "d",
        "score": score,
        "score_type": "cosine",
        "source": "vector",
        "content": content if content is not None else f"content-{cid}",
    }


def _bare_service() -> RetrievalService:
    """A RetrievalService with __init__ bypassed; only loop deps are set."""
    svc = RetrievalService.__new__(RetrievalService)
    svc.config = SimpleNamespace(rerank_score_floor=None)
    svc.reranker = None
    return svc


def _result(chunks: list[dict]) -> RetrievalResult:
    return RetrievalResult(chunks=list(chunks), query="q", tenant_id="t", latency_ms=0.0)


@pytest.mark.parametrize(
    "items",
    [
        None,
        [],
        [SimpleNamespace(index=-1, score=0.5), SimpleNamespace(index=1, score=0.4)],
        [SimpleNamespace(index=True, score=0.5), SimpleNamespace(index=1, score=0.4)],
        [SimpleNamespace(index=0, score=0.5), SimpleNamespace(index=0, score=0.4)],
        [SimpleNamespace(index=0, score=float("nan")), SimpleNamespace(index=1, score=0.4)],
        [SimpleNamespace(index=0, score=float("inf")), SimpleNamespace(index=1, score=0.4)],
        [SimpleNamespace(index=0, score="invalid"), SimpleNamespace(index=1, score=0.4)],
        [SimpleNamespace(index=0, score=0.5)],
    ],
)
def test_rerank_validation_rejects_malformed_or_partial_results(items):
    assert _validated_rerank_results(items, input_count=2, top_k=2) is None


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
    # Without a common reranker, the initial group keeps priority.
    assert [c["chunk_id"] for c in result.chunks] == ["a", "b"]
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


@pytest.mark.asyncio
async def test_unknown_sufficiency_stops_without_search_and_traces_coverage():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=None,
        reason="invalid_decision",
        coverage=[{"chunk_id": "a", "truncated": True}],
    )
    svc._execute_vector_search = AsyncMock()
    result = _result([_chunk("a", 0.9)])

    trace = await _run(svc, result)

    svc._execute_vector_search.assert_not_called()
    assert trace[0]["status"] == "unknown"
    assert trace[0]["coverage"] == [{"chunk_id": "a", "truncated": True}]


@pytest.mark.asyncio
async def test_gap_pool_dedups_queries_accumulates_rerank_time_and_marks_unchecked_context():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False,
        gap_queries=[" gap one ", "gap one", "gap two", "gap three", "gap four"],
    )
    async def _search(*, structured_query, **_kwargs):
        return RetrievalResult(
            chunks=[_chunk(structured_query.cleaned_query, 0.1)],
            query=structured_query.cleaned_query,
            tenant_id="t",
            latency_ms=0.0,
            reranking_ms=2.5,
        )
    svc._execute_vector_search = AsyncMock(side_effect=_search)
    async def _rerank(*, documents, **_kwargs):
        return SimpleNamespace(
            results=[SimpleNamespace(index=i, score=0.9 - i * 0.01) for i in range(len(documents))]
        )
    svc.reranker = AsyncMock()
    svc.reranker.rerank.side_effect = _rerank
    result = _result([_chunk("base", 0.8)])
    result.reranking_ms = 1.0

    trace = await _run(svc, result, max_rounds=1)

    assert svc._execute_vector_search.await_count == 3
    assert result.reranking_ms >= 8.5
    sufficiency_trace = next(step for step in trace if step["step"] == "sufficiency_check")
    assert sufficiency_trace["fresh_gap_queries"] == [" gap one ", "gap two", "gap three"]
    assert sufficiency_trace["context_reevaluated"] is False
    assert sufficiency_trace["context_changed_after_evaluation"] is True


@pytest.mark.asyncio
async def test_common_merge_reranks_union_then_applies_floor_without_mutating_sources():
    svc = _bare_service()
    svc.config = SimpleNamespace(rerank_score_floor=0.5)
    svc.reranker = AsyncMock()
    svc.reranker.rerank.return_value = SimpleNamespace(
        results=[
            SimpleNamespace(index=2, score=0.9),
            SimpleNamespace(index=0, score=0.2),
            SimpleNamespace(index=1, score=0.7),
        ]
    )
    base = _chunk("a", 0.99, "base")
    base["source"] = "vector"
    gap = _chunk("b", 0.1, "gap")
    gap["source"] = "cache"

    other_base = _chunk("x", 0.8, "other base")
    merged, elapsed, reranked = await svc._merge_candidate_groups(
        [[base, other_base], [gap]], query="common query", top_k=3
    )

    assert svc.reranker.rerank.await_args.kwargs["query"] == "common query"
    assert [c["chunk_id"] for c in merged] == ["b", "x"]
    assert merged[0]["source"] == "cache"
    assert base["score"] == 0.99
    assert elapsed >= 0
    assert reranked is True


@pytest.mark.asyncio
async def test_partial_common_rerank_falls_back_to_group_order():
    svc = _bare_service()
    svc.config = SimpleNamespace(rerank_score_floor=None)
    svc.reranker = AsyncMock()
    svc.reranker.rerank.return_value = SimpleNamespace(
        results=[SimpleNamespace(index=1, score=0.9)]
    )
    merged, _, reranked = await svc._merge_candidate_groups(
        [[_chunk("a", 0.1)], [_chunk("b", 0.99)]],
        query="common query",
        top_k=2,
    )

    assert [c["chunk_id"] for c in merged] == ["a", "b"]
    assert reranked is False


@pytest.mark.asyncio
async def test_common_merge_fallback_keeps_base_then_round_robin_and_exact_doc_dedup():
    svc = _bare_service()
    svc.config = SimpleNamespace(rerank_score_floor=0.5)
    svc.reranker = None
    same_doc = _chunk("b", 0.01, "same text")
    exact_duplicate = _chunk("e", 0.5, "same text")
    other_doc = _chunk("c", 0.99, "same text")
    other_doc["document_id"] = "other"
    changed_text = _chunk("d", 0.1, " same text")
    changed_case = _chunk("f", 0.2, "SAME text")
    empty_ids = [_chunk("", 0.1, "first"), _chunk("", 0.1, "second")]
    empty_docs = [_chunk("n1", 0.1, "same"), _chunk("n2", 0.1, "same")]
    for candidate in empty_docs:
        candidate["document_id"] = ""
    empty_contents = [_chunk("z1", 0.1, ""), _chunk("z2", 0.1, "")]

    merged, _, reranked = await svc._merge_candidate_groups(
        [[_chunk("a", 0.1)], [
            same_doc, exact_duplicate, other_doc, changed_text, changed_case,
            *empty_ids, *empty_docs, *empty_contents,
        ]],
        query="common query",
        top_k=12,
    )

    assert [c["chunk_id"] for c in merged] == [
        "a", "b", "c", "d", "f", "", "", "n1", "n2", "z1", "z2",
    ]
    assert reranked is False


@pytest.mark.asyncio
async def test_gap_hits_are_added_round_robin_without_common_rerank():
    svc = _bare_service()
    svc.reranker = AsyncMock()  # present, but the loop must not re-score gap hits
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False, gap_queries=["g1", "g2", "g3"]
    )
    groups = {
        "g1": [_chunk("a", 0.99), _chunk("g1-top", 0.9), _chunk("g1-2nd", 0.8)],  # rank 1 already in base
        "g2": [_chunk("g2-top", 0.2), _chunk("g2-2nd", 0.1)],
        "g3": [_chunk("g3-top", 0.5)],
    }

    async def _search(*, structured_query, **_kwargs):
        return _result(groups[structured_query.cleaned_query])

    svc._execute_vector_search = AsyncMock(side_effect=_search)
    result = _result([_chunk("a", 0.9), _chunk("b", 0.8)])

    trace = await _run(svc, result, max_rounds=1, top_k=2)

    svc.reranker.rerank.assert_not_called()
    # base kept in order; round-robin over each gap query's top_k hits by rank
    # (g1 backfills past "a"; its 3rd hit is beyond top_k=2)
    order = ["g1-top", "g2-top", "g3-top", "g2-2nd"]
    assert [c["chunk_id"] for c in result.chunks] == ["a", "b", *order]
    assert [c.get("sufficiency_gap_hit", False) for c in result.chunks] == [False, False] + [True] * 4
    check = next(step for step in trace if step["step"] == "sufficiency_check")
    assert check["gap_hits_added"] == order


@pytest.mark.asyncio
async def test_each_round_adds_at_most_six_gap_hits():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, gap_queries=["g1"]),
        SufficiencyVerdict(is_sufficient=False, gap_queries=["g2"]),
    ]

    async def _search(*, structured_query, **_kwargs):
        q = structured_query.cleaned_query
        return _result([_chunk(f"{q}-{i}", 0.9 - i / 100) for i in range(8)])

    svc._execute_vector_search = AsyncMock(side_effect=_search)
    result = _result([_chunk("a", 0.9)])

    await _run(svc, result, max_rounds=2, top_k=8)

    # round 1 adds 6 of g1's 8 hits, round 2 adds 6 of g2's (budget 8 + 2*6 = 20)
    assert [c["chunk_id"] for c in result.chunks] == (
        ["a"] + [f"g1-{i}" for i in range(6)] + [f"g2-{i}" for i in range(6)]
    )


@pytest.mark.asyncio
async def test_resurfaced_leftover_gap_hit_keeps_the_loop_going():
    # Round 1 admits 6 of 8 hits; later rounds resurface the leftovers. They are new
    # to the context, so the loop must keep going instead of treating them as seen.
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.side_effect = [
        SufficiencyVerdict(is_sufficient=False, gap_queries=["g1"]),
        SufficiencyVerdict(is_sufficient=False, gap_queries=["g2"]),
        SufficiencyVerdict(is_sufficient=False, gap_queries=["g3"]),
    ]
    first = [_chunk(f"g1-{i}", 0.9 - i / 100) for i in range(8)]
    results = {"g1": first, "g2": [first[6]], "g3": [first[7]]}

    async def _search(*, structured_query, **_kwargs):
        return _result(results[structured_query.cleaned_query])

    svc._execute_vector_search = AsyncMock(side_effect=_search)
    result = _result([_chunk("a", 0.9)])

    await _run(svc, result, max_rounds=3, top_k=8)

    assert svc.sufficiency_evaluator.evaluate.await_count == 3
    assert [c["chunk_id"] for c in result.chunks] == ["a"] + [f"g1-{i}" for i in range(8)]


@pytest.mark.asyncio
async def test_saturated_budget_stops_after_first_round():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False, gap_queries=["g"]
    )
    svc._execute_vector_search = AsyncMock(return_value=_result([_chunk("c", 0.99)]))
    result = _result([_chunk("a", 0.9), _chunk("b", 0.8)])
    opts = QueryOptions(use_sufficiency_loop=True, max_sufficiency_rounds=3, sufficiency_max_chunks=2)
    await svc._run_sufficiency_loop(
        result=result, processed_query="q", tenant_id="t", document_ids=None,
        filters={}, top_k=2, options=opts, trace=[],
        vector_targets=[VectorSearchTarget(tenant_id="t", collection_name="c")],
        tenant_config=None, include_trace=False,
    )
    # nothing can be admitted, so no further judge calls or searches
    assert svc.sufficiency_evaluator.evaluate.await_count == 1
    assert svc._execute_vector_search.await_count == 1
    assert [c["chunk_id"] for c in result.chunks] == ["a", "b"]


def _reranked(cid: str, score: float) -> dict:
    return {**_chunk(cid, score), "score_type": "reranker"}


@pytest.mark.asyncio
async def test_off_topic_gap_hits_below_floor_are_not_admitted_and_loop_stops():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False, gap_queries=["g"]
    )
    svc._execute_vector_search = AsyncMock(
        return_value=_result([_reranked("noise-1", 0.09), _reranked("noise-2", 1e-5)])
    )
    result = _result([_chunk("a", 0.9)])

    trace = await _run(svc, result, max_rounds=3, top_k=5)

    assert [c["chunk_id"] for c in result.chunks] == ["a"]
    assert svc.sufficiency_evaluator.evaluate.await_count == 1
    check = next(step for step in trace if step["step"] == "sufficiency_check")
    assert check["gap_hits_added"] == []
    assert check["gap_hits_below_floor"] == 2


@pytest.mark.asyncio
async def test_gap_floor_keeps_on_topic_reranked_and_non_reranker_scores():
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False, gap_queries=["g1", "g2"]
    )
    groups = {
        # reranked group: on-topic hit kept, noise dropped
        "g1": [_reranked("on-topic", 0.61), _reranked("noise", 0.05)],
        # rerank fallback (RRF scale ~0.03): never compared with the floor
        "g2": [{**_chunk("rrf", 0.03), "score_type": "rrf"}],
    }

    async def _search(*, structured_query, **_kwargs):
        return _result(groups[structured_query.cleaned_query])

    svc._execute_vector_search = AsyncMock(side_effect=_search)
    result = _result([_chunk("a", 0.9)])

    await _run(svc, result, max_rounds=1, top_k=5)

    assert [c["chunk_id"] for c in result.chunks] == ["a", "on-topic", "rrf"]


@pytest.mark.asyncio
async def test_gap_floor_rejects_weak_band_hits():
    # 0.25-0.6 held only irrelevant hits in the held-out benchmark.
    svc = _bare_service()
    svc.sufficiency_evaluator = AsyncMock()
    svc.sufficiency_evaluator.evaluate.return_value = SufficiencyVerdict(
        is_sufficient=False, gap_queries=["g"]
    )
    svc._execute_vector_search = AsyncMock(
        return_value=_result([_reranked("weak-1", 0.57), _reranked("weak-2", 0.31)])
    )
    result = _result([_chunk("a", 0.9)])

    await _run(svc, result, max_rounds=1, top_k=5)

    assert [c["chunk_id"] for c in result.chunks] == ["a"]
