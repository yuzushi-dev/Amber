"""Tests for the retrieval service — taxonomy routing (formerly contained
_execute_hybrid_search tests which were removed along with that dead method).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application import retrieval_service as retrieval_module
from src.core.retrieval.application.query.parser import QueryParser
from src.core.retrieval.application.retrieval_service import RetrievalService
from src.core.retrieval.domain.ports.vector_store_port import SearchResult
from src.shared.kernel.models.query import QueryOptions

# ---------------------------------------------------------------------------
# Taxonomy routing unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taxonomy_routing_called_for_admin_query():
    """resolve_product_context is triggered and list_visible_document_ids_by_taxonomy is called."""


    vector_store = MagicMock()
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=["doc-admin"])

    mock_factory = MagicMock()
    mock_factory.get_embedding_provider.return_value = MagicMock()
    mock_factory.get_llm_provider.return_value = MagicMock()

    with (
        patch(
            "src.core.retrieval.application.retrieval_service.build_provider_factory",
            return_value=mock_factory,
        ),
        patch("src.core.retrieval.application.retrieval_service.SemanticCache"),
        patch("src.core.retrieval.application.retrieval_service.ResultCache"),
    ):
        service = RetrievalService(
            document_repository=document_repository,
            vector_store=vector_store,
            neo4j_client=graph_store,
            openai_api_key="sk-test",
        )

    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 8)
    service.vector_searcher.search = AsyncMock(return_value=[])
    service.reranker = None
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock(return_value=None)
    service.embedding_cache.get = AsyncMock(return_value=None)
    service.embedding_cache.set = AsyncMock(return_value=None)

    with patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes") as mock_scopes:
        mock_scopes.return_value = MagicMock(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
        )
        result = await service.retrieve(
            query="How do delegate admins work?",
            tenant_id="default",
            include_trace=True,
        )

    document_repository.list_visible_document_ids_by_taxonomy.assert_called()
    # Verify trace contains taxonomy_routing step
    taxonomy_steps = [s for s in result.trace if s.get("step") == "taxonomy_routing"]
    assert taxonomy_steps, "taxonomy_routing step missing from trace"
    assert taxonomy_steps[0]["inferred_audience"] == "admin"
    assert any(step.get("step") == "query_variants" for step in result.trace)
    assert any(step.get("step") == "pre_rerank_candidates" for step in result.trace)
    assert any(step.get("step") == "post_rerank_candidates" for step in result.trace)
    assert any(step.get("step") == "final_selection" for step in result.trace)


@pytest.mark.asyncio
async def test_taxonomy_explicit_filter_overrides_inference():
    """Explicit edition in filters dict overrides query-inferred context."""


    vector_store = MagicMock()
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=["doc-ce"])

    mock_factory = MagicMock()
    mock_factory.get_embedding_provider.return_value = MagicMock()
    mock_factory.get_llm_provider.return_value = MagicMock()

    with (
        patch(
            "src.core.retrieval.application.retrieval_service.build_provider_factory",
            return_value=mock_factory,
        ),
        patch("src.core.retrieval.application.retrieval_service.SemanticCache"),
        patch("src.core.retrieval.application.retrieval_service.ResultCache"),
    ):
        service = RetrievalService(
            document_repository=document_repository,
            vector_store=vector_store,
            neo4j_client=graph_store,
            openai_api_key="sk-test",
        )

    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 8)
    service.vector_searcher.search = AsyncMock(return_value=[])
    service.reranker = None
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock(return_value=None)
    service.embedding_cache.get = AsyncMock(return_value=None)
    service.embedding_cache.set = AsyncMock(return_value=None)

    with patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes") as mock_scopes:
        mock_scopes.return_value = MagicMock(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
        )
        # Query text alone would infer commercial, but explicit override says ce
        await service.retrieve(
            query="How do delegate admins work?",
            tenant_id="default",
            filters={"edition": "ce"},
        )

    call_kwargs = document_repository.list_visible_document_ids_by_taxonomy.call_args
    assert call_kwargs.kwargs.get("edition") == "ce"


@pytest.mark.asyncio
async def test_decomposition_reranks_variants_then_common_union_and_caches_reranked_scores():
    service = RetrievalService.__new__(RetrievalService)
    service.sparse_embedding = None
    service.config = SimpleNamespace(
        enable_hybrid=False, initial_k=10, rerank_model="test", rerank_score_floor=0.8,
    )
    embedding = SimpleNamespace(
        model="test", provider=SimpleNamespace(provider_name="test"),
        embed_single=AsyncMock(return_value=[0.1]),
    )
    service._resolve_embedding_service = MagicMock(return_value=embedding)
    service.embedding_cache = SimpleNamespace(
        get=AsyncMock(return_value=None), set=AsyncMock(),
    )
    cache_values = {}

    async def _cache_get(query, *_args, **_kwargs):
        return cache_values.get(query)

    async def _cache_set(**kwargs):
        cache_values[kwargs["query"]] = SimpleNamespace(
            chunk_ids=kwargs["chunk_ids"], scores=kwargs["scores"],
            score_types=kwargs["score_types"], sources=kwargs["sources"],
        )

    service.result_cache = SimpleNamespace(
        get=AsyncMock(side_effect=_cache_get), set=AsyncMock(side_effect=_cache_set),
    )
    service.decomposer = SimpleNamespace(
        decompose=AsyncMock(return_value=["variant one", "variant two"]),
    )
    service._search_vector_targets = AsyncMock(side_effect=[
        ([SearchResult(
            chunk_id="raw-top", document_id="doc-one", tenant_id="tenant", score=1.0,
            metadata={"content": "raw top evidence"}, source="vector",
        ), SearchResult(
            chunk_id="promoted", document_id="doc-one", tenant_id="tenant", score=0.1,
            metadata={"content": "promoted evidence"}, source="vector",
        )], []),
        ([SearchResult(
            chunk_id="two", document_id="doc-two", tenant_id="tenant", score=0.6,
            metadata={"content": "evidence two"}, source="vector",
        )], []),
    ])

    async def _fetch_chunks_by_ids(chunk_ids, scores, score_types, sources):
        content_by_id = {"promoted": "promoted evidence", "two": "evidence two"}
        return [
            {
                "chunk_id": chunk_id, "document_id": "doc-one", "content": content_by_id[chunk_id],
                "score": score, "score_type": score_type, "source": source,
            }
            for chunk_id, score, score_type, source in zip(
                chunk_ids, scores, score_types, sources, strict=True
            )
        ]

    service._fetch_chunks_by_ids = AsyncMock(side_effect=_fetch_chunks_by_ids)

    async def _rerank(*, query, documents, **_kwargs):
        timings = {
            "ranker_load_ms": 1.25,
            "executor_queue_ms": 2.5,
            "ranker_execution_ms": 12.75,
            "postprocess_ms": 0.5,
            "unexpected": "discarded",
        }
        if query == "variant one":
            results = [SimpleNamespace(index=1, score=0.99)]
        elif query == "variant two":
            results = [SimpleNamespace(index=0, score=0.95)]
        else:
            results = [
                SimpleNamespace(index=0, score=0.9),
                SimpleNamespace(index=1, score=0.85),
            ]
        return SimpleNamespace(results=results, metadata=timings)

    service.reranker = SimpleNamespace(rerank=AsyncMock(side_effect=_rerank))

    trace = []
    result = await service._execute_vector_search(
        structured_query=QueryParser.parse("original question"),
        tenant_id="tenant", document_ids=None, filters={}, top_k=1, trace=trace,
        vector_targets=[], tenant_config=None,
        options=QueryOptions(use_hyde=False, use_decomposition=True),
        include_trace=True,
    )

    assert service.reranker.rerank.await_count == 3
    common_call = service.reranker.rerank.await_args_list[-1]
    assert common_call.kwargs["query"] == "original question"
    assert [chunk["chunk_id"] for chunk in result.chunks] == ["promoted"]
    assert result.chunks[0]["source"] == "vector"
    assert cache_values["variant one"].chunk_ids == ["promoted"]
    assert cache_values["variant one"].score_types == ["reranker"]
    initial_reranks = [step for step in trace if step.get("step") == "rerank"]
    assert len(initial_reranks) == 2
    assert all(step["stage"] == "initial" for step in initial_reranks)
    common_rerank = next(step for step in trace if step.get("step") == "common_query_rerank")
    assert common_rerank["stage"] == "query_variant_common"
    for step in [*initial_reranks, common_rerank]:
        assert step["ranker_load_ms"] == 1.25
        assert step["executor_queue_ms"] == 2.5
        assert step["ranker_execution_ms"] == 12.75
        assert step["postprocess_ms"] == 0.5
        assert "unexpected" not in step

    single_query_result = await service._execute_vector_search(
        structured_query=QueryParser.parse("variant one"), tenant_id="tenant",
        document_ids=None, filters={}, top_k=1, trace=[], vector_targets=[],
        tenant_config=None,
        options=QueryOptions(use_hyde=False, use_decomposition=False),
    )
    assert [chunk["chunk_id"] for chunk in single_query_result.chunks] == ["promoted"]
    assert single_query_result.chunks[0]["score_type"] == "reranker"
    assert service.reranker.rerank.await_count == 3


@pytest.mark.asyncio
async def test_invalid_single_query_rerank_falls_back_before_cache_write(monkeypatch):
    class FakeClock:
        now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = FakeClock()
    monkeypatch.setattr(retrieval_module, "time", clock)
    service = RetrievalService.__new__(RetrievalService)
    service.sparse_embedding = None
    service.config = SimpleNamespace(
        enable_hybrid=False, initial_k=10, rerank_model="test", rerank_score_floor=0.5,
    )
    embedding = SimpleNamespace(
        model="test", provider=SimpleNamespace(provider_name="test"),
        embed_single=AsyncMock(return_value=[0.1]),
    )
    service._resolve_embedding_service = MagicMock(return_value=embedding)
    service.embedding_cache = SimpleNamespace(
        get=AsyncMock(return_value=None), set=AsyncMock(),
    )
    service.result_cache = SimpleNamespace(
        get=AsyncMock(return_value=None), set=AsyncMock(),
    )
    service._search_vector_targets = AsyncMock(return_value=(
        [
            SearchResult(
                chunk_id="first", document_id="doc", tenant_id="tenant", score=0.9,
                metadata={"content": "first evidence"},
            ),
            SearchResult(
                chunk_id="second", document_id="doc", tenant_id="tenant", score=0.8,
                metadata={"content": "second evidence"},
            ),
        ],
        [],
    ))
    async def _invalid_rerank(**_kwargs):
        clock.advance(0.005)
        return SimpleNamespace(results=[
            SimpleNamespace(index=-1, score=0.99),
            SimpleNamespace(index=0, score=0.98),
        ])

    service.reranker = SimpleNamespace(rerank=AsyncMock(side_effect=_invalid_rerank))

    trace = []
    result = await service._execute_vector_search(
        structured_query=QueryParser.parse("single query"), tenant_id="tenant",
        document_ids=None, filters={}, top_k=2, trace=trace, vector_targets=[],
        tenant_config=None, options=QueryOptions(use_hyde=False, use_decomposition=False),
        include_trace=True,
    )

    assert [chunk["chunk_id"] for chunk in result.chunks] == ["first", "second"]
    assert [chunk["score_type"] for chunk in result.chunks] == ["cosine", "cosine"]
    assert service.result_cache.set.await_args.kwargs["score_types"] == ["cosine", "cosine"]
    assert result.reranking_ms == pytest.approx(5.0)
    failed_rerank = next(step for step in trace if step.get("step") == "rerank")
    assert failed_rerank == {
        "step": "rerank",
        "stage": "initial",
        "duration_ms": pytest.approx(5.0),
        "model": "test",
        "rerank_attempted": True,
        "status": "failed",
    }
    assert "malformed" not in repr(failed_rerank)
