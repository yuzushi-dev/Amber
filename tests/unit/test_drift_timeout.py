"""Bounded DRIFT forwarding, scope, cancellation, and timeout tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application.retrieval_service import RetrievalResult
from src.shared.kernel.models.query import QueryOptions, SearchMode


def retrieval_result(*chunks, trace=None, reranking_ms=0.0, query="child"):
    return RetrievalResult(
        chunks=list(chunks),
        query=query,
        tenant_id="tenant",
        latency_ms=1.0,
        trace=trace or [],
        reranking_ms=reranking_ms,
    )


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.default_llm_provider = "openai"
    return settings


@pytest.fixture
def drift_service():
    from src.core.retrieval.application.search.drift_search import DriftSearchService

    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(return_value=retrieval_result(
        {"chunk_id": "primer", "content": "primer evidence"},
        trace=[{"step": "vector", "duration_ms": 1}],
        reranking_ms=2.5,
    ))
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=MagicMock(text="DONE"))
    service = DriftSearchService(retrieval, provider, timeout_seconds=1)
    return service, retrieval, provider


@pytest.mark.asyncio
async def test_primer_forwards_scope_filters_flags_and_copied_basic_options(drift_service, mock_settings):
    service, retrieval, _ = drift_service
    options = QueryOptions(
        search_mode=SearchMode.DRIFT,
        use_sufficiency_loop=True,
        use_hyde=True,
        use_rewrite=False,
        include_trace=True,
    )
    scopes = MagicMock()
    with patch("src.shared.kernel.runtime.get_settings", return_value=mock_settings):
        result = await service.search(
            "query", "tenant", options=options, query_scopes=scopes,
            document_ids=["doc-1"], filters={"edition": "commercial"},
            for_generation=True, include_trace=True,
        )

    kwargs = retrieval.retrieve.await_args.kwargs
    assert kwargs == {
        "query": "query", "tenant_id": "tenant", "top_k": 5,
        "document_ids": ["doc-1"], "filters": {"edition": "commercial"},
        "options": kwargs["options"], "query_scopes": scopes,
        "for_generation": True, "include_trace": True,
    }
    child_options = kwargs["options"]
    assert child_options is not options
    assert child_options.search_mode == SearchMode.BASIC
    assert child_options.use_sufficiency_loop is False
    assert child_options.use_hyde is True and child_options.use_rewrite is False
    assert options.search_mode == SearchMode.DRIFT and options.use_sufficiency_loop is True
    assert result["reranking_ms"] == 2.5
    assert result["trace"] == [{"step": "vector", "duration_ms": 1,
                                "drift_phase": "primer", "drift_query": "query"}]


@pytest.mark.asyncio
async def test_empty_document_scope_fails_closed_without_retrieve_or_llm(drift_service):
    service, retrieval, provider = drift_service
    result = await service.search("query", "tenant", document_ids=[])
    assert result["candidates"] == []
    retrieval.retrieve.assert_not_awaited()
    provider.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_primer_timeout_is_traced_and_skips_llm(drift_service, mock_settings):
    service, retrieval, provider = drift_service

    async def slow_primer(**kwargs):
        await asyncio.sleep(0.05)
        return retrieval_result()

    retrieval.retrieve.side_effect = slow_primer
    service.timeout_seconds = 0.005
    with patch("src.shared.kernel.runtime.get_settings", return_value=mock_settings):
        result = await service.search("query", "tenant")

    assert result["timed_out_stage"] == "primer"
    assert result["trace"][-1] == {"step": "drift_timeout", "stage": "primer"}
    provider.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_generator_timeout_returns_primer_evidence(drift_service, mock_settings):
    service, _, provider = drift_service

    async def slow_generate(*args, **kwargs):
        await asyncio.sleep(0.05)

    provider.generate.side_effect = slow_generate
    service.timeout_seconds = 0.02
    with patch("src.shared.kernel.runtime.get_settings", return_value=mock_settings):
        result = await service.search("query", "tenant")

    assert [c["chunk_id"] for c in result["candidates"]] == ["primer"]
    assert result["timed_out_stage"] == "generate"
    assert result["trace"][-1]["stage"] == "generate"


@pytest.mark.asyncio
async def test_expansion_timeout_keeps_completed_child_evidence(drift_service, mock_settings):
    service, retrieval, provider = drift_service
    calls = 0

    async def retrieve(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return retrieval_result({"chunk_id": "primer", "content": "primer"})
        if kwargs["query"].startswith("Q1"):
            await asyncio.sleep(0.001)
            return retrieval_result({"chunk_id": "expanded", "content": "new evidence"})
        await asyncio.sleep(0.05)
        return retrieval_result({"chunk_id": "late", "content": "late"})

    retrieval.retrieve.side_effect = retrieve
    provider.generate.return_value = MagicMock(text="Q1 #generated\nQ2")
    service.timeout_seconds = 0.02
    with patch("src.shared.kernel.runtime.get_settings", return_value=mock_settings):
        result = await service.search(
            "query", "tenant", include_trace=True, document_ids=["doc"],
            filters={"tags": []}, for_generation=True,
        )

    assert {c["chunk_id"] for c in result["candidates"]} == {"primer", "expanded"}
    assert result["timed_out_stage"] == "expansion"
    assert result["trace"][-1]["stage"] == "expansion"
    expansion_calls = [call.kwargs for call in retrieval.retrieve.await_args_list[1:]]
    assert len(expansion_calls) == 2
    assert all(call["document_ids"] == ["doc"] for call in expansion_calls)
    assert all(call["filters"] == {"tags": []} for call in expansion_calls)
    assert all(call["for_generation"] is True for call in expansion_calls)
    assert all(call["options"].search_mode == SearchMode.BASIC for call in expansion_calls)


@pytest.mark.asyncio
async def test_search_cancellation_propagates(drift_service):
    service, retrieval, _ = drift_service
    started = asyncio.Event()

    async def blocked(**kwargs):
        started.set()
        await asyncio.Event().wait()

    retrieval.retrieve.side_effect = blocked
    task = asyncio.create_task(service.search("query", "tenant"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_expansion_child_cancellation_propagates(drift_service, mock_settings):
    service, retrieval, provider = drift_service
    child_started = asyncio.Event()
    child_cancelled = 0

    async def retrieve(**kwargs):
        nonlocal child_cancelled
        if kwargs["top_k"] == 5:
            return retrieval_result({"chunk_id": "primer", "content": "primer"})
        child_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            child_cancelled += 1
            raise

    retrieval.retrieve.side_effect = retrieve
    provider.generate.return_value = MagicMock(text="Q1\nQ2")
    with patch("src.shared.kernel.runtime.get_settings", return_value=mock_settings):
        task = asyncio.create_task(service.search("query", "tenant"))
        await child_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert child_cancelled == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("explicit_tags", "expected_tags"),
    [([], []), (None, ["fromquery"])],
)
async def test_retrieval_dispatch_forwards_resolved_scope_and_tag_precedence(
    explicit_tags, expected_tags,
):
    from src.core.retrieval.application.retrieval_service import RetrievalService

    service = RetrievalService.__new__(RetrievalService)
    service.config = SimpleNamespace(top_k=5)
    service._get_effective_tenant_config = AsyncMock(return_value={})
    service.document_repository = SimpleNamespace()
    scopes = SimpleNamespace(
        effective_tenant_id="tenant", vector_scopes=["tenant"],
        graph_scopes=["tenant"], group_ids=[], enforce_groups=False,
    )
    service.router = SimpleNamespace(route=AsyncMock(return_value=SearchMode.DRIFT))
    service.drift_search = SimpleNamespace(search=AsyncMock(return_value={
        "candidates": [{"chunk_id": "drift", "content": "evidence"}],
        "follow_ups": [], "trace": [{"step": "primer"}], "reranking_ms": 7.0,
    }))
    service.circuit_breaker = MagicMock()

    result = await service.retrieve(
        "find facts #fromquery", "tenant", document_ids=["doc-1"],
        filters={"tags": explicit_tags, "edition": "commercial", "audience": "admin"},
        options=QueryOptions(search_mode=SearchMode.DRIFT, use_hyde=True),
        query_scopes=scopes, include_trace=True,
    )

    kwargs = service.drift_search.search.await_args.kwargs
    assert kwargs["document_ids"] == ["doc-1"]
    assert kwargs["filters"] == {
        "tags": expected_tags, "edition": "commercial", "audience": "admin",
    }
    assert kwargs["query_scopes"] is scopes
    assert kwargs["options"].search_mode == SearchMode.DRIFT
    assert kwargs["for_generation"] is False and kwargs["include_trace"] is True
    assert result.trace[-1] == {"step": "primer"}
    assert result.reranking_ms == 7.0
