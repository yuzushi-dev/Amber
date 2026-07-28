"""Tests for RetrievalConfig.rerank_score_floor.

Why the floor lives after reranking and nowhere else: the cosine threshold
(`score_threshold`) is only valid on the dense path, and the hybrid path's fused
score is on a third scale (see the scale note in _search_vector_targets_hybrid).
The reranker score is the only one carried downstream of BOTH paths, so it is the
only place a single configured floor can gate every query.

Measured on the prod corpus with ms-marco-MiniLM-L-12-v2: chunks for a covered
query score >= 0.82, chunks for a query with no coverage score ~0.0.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application.retrieval_service import RetrievalConfig, RetrievalService
from src.core.retrieval.infrastructure.vector_store.milvus import SearchResult
from src.core.tenants.application.query_scopes import QueryScopes


def _make_service(floor: float | None):
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=[])
    document_repository.list_non_ready_document_ids_with_chunks = AsyncMock(return_value=[])

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
            vector_store=MagicMock(),
            neo4j_client=MagicMock(),
            openai_api_key="sk-test",
            config=RetrievalConfig(rerank_score_floor=floor),
        )

    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 8)
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock(return_value=None)
    service.embedding_cache.get = AsyncMock(return_value=None)
    service.embedding_cache.set = AsyncMock(return_value=None)
    return service


def _wire_search_and_rerank(service, rerank_scores: list[float]):
    """Vector search returns N hits; the reranker scores them as given."""
    hits = [
        SearchResult(
            chunk_id=f"chunk-{i}",
            document_id=f"doc-{i}",
            tenant_id="default",
            score=0.5,  # raw vector score: deliberately different scale
            metadata={"content": f"content {i}"},
        )
        for i in range(len(rerank_scores))
    ]
    service.vector_searcher.search = AsyncMock(return_value=hits)

    reranked = MagicMock()
    reranked.results = [
        MagicMock(index=i, score=score) for i, score in enumerate(rerank_scores)
    ]
    service.reranker = MagicMock()
    service.reranker.rerank = AsyncMock(return_value=reranked)


async def _retrieve(service):
    with patch(
        "src.core.retrieval.application.retrieval_service.resolve_query_scopes"
    ) as mock_scopes:
        # A real QueryScopes, not a MagicMock: with a mock, `enforce_groups` is a
        # truthy Mock and _resolve_vector_targets takes the fail-closed branch,
        # resolving zero targets - the search is then never reached and a floor
        # test would pass with an empty result for the wrong reason.
        mock_scopes.return_value = QueryScopes(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=[],
            shared_document_owner_tenants=[],
            group_ids=[],
            enforce_groups=False,
        )
        return await service.retrieve(
            query="How do I enable alerting?",
            tenant_id="default",
            top_k=5,
            include_trace=True,
        )


@pytest.mark.asyncio
async def test_floor_drops_below_threshold_chunks():
    service = _make_service(floor=0.5)
    _wire_search_and_rerank(service, [0.99, 0.85, 0.40, 0.01])

    result = await _retrieve(service)

    scores = [float(c["score"]) for c in result.chunks]
    assert scores == [0.99, 0.85], f"floor did not drop the low-scored chunks: {scores}"
    rerank_step = next(s for s in result.trace if s.get("step") == "rerank")
    assert rerank_step["dropped_below_floor"] == 2
    assert rerank_step["floor"] == 0.5


@pytest.mark.asyncio
async def test_no_coverage_query_yields_zero_chunks():
    """The case that matters: every chunk scores ~0, so generation gets nothing
    and the LLM call is never made."""
    service = _make_service(floor=0.5)
    _wire_search_and_rerank(service, [0.0, 0.0, 0.0])

    result = await _retrieve(service)

    assert result.chunks == [], f"expected an empty result, got {len(result.chunks)} chunks"


@pytest.mark.asyncio
async def test_floor_disabled_keeps_everything():
    """Default config must not change behaviour."""
    service = _make_service(floor=None)
    _wire_search_and_rerank(service, [0.99, 0.40, 0.0])

    result = await _retrieve(service)

    assert len(result.chunks) == 3
    rerank_step = next(s for s in result.trace if s.get("step") == "rerank")
    assert "dropped_below_floor" not in rerank_step


@pytest.mark.asyncio
async def test_floor_applies_to_cache_hits():
    """Cached scores are post-rerank scores, so a cache hit must not bypass the
    gate - otherwise the floor is enforced only on the first query."""
    service = _make_service(floor=0.5)
    _wire_search_and_rerank(service, [0.99])

    cached = MagicMock()
    cached.chunk_ids = ["chunk-a", "chunk-b"]
    cached.scores = [0.95, 0.02]
    service.result_cache.get = AsyncMock(return_value=cached)
    service.document_repository.get_chunks = AsyncMock(
        return_value=[
            MagicMock(id="chunk-a", document_id="doc-a", content="a", metadata_={}),
            MagicMock(id="chunk-b", document_id="doc-b", content="b", metadata_={}),
        ]
    )

    result = await _retrieve(service)

    kept = [c["chunk_id"] for c in result.chunks]
    assert kept == ["chunk-a"], f"cache hit bypassed the floor: {kept}"
