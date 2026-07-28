"""
Unit tests for the result-cache staleness fix in RetrievalService.

Found via an A/B run against the mirror: a cache hit whose `chunk_ids` no
longer resolve to any real chunk in the repository (e.g. a re-ingest
replaced them with new ids) used to be treated as a full cache hit that
happened to have zero chunks, and the code `continue`d past the sub-query
without ever falling back to a real search. If that was the only sub-query,
the whole request came back with "No relevant documents found." even though
matching documents exist. The fix in retrieval_service.py treats a cache hit
that resolves to zero chunks as a miss (unless the cache itself legitimately
recorded zero chunk_ids to begin with) and falls through to a live search.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.cache.result_cache import CachedResult
from src.core.retrieval.application.retrieval_service import RetrievalService
from src.core.retrieval.domain.ports.vector_store_port import SearchResult
from src.core.tenants.application.query_scopes import QueryScopes


def _build_service(document_repository) -> RetrievalService:
    vector_store = MagicMock()
    graph_store = MagicMock()

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

    service.reranker = None
    service.sparse_embedding = None
    service.embedding_cache.get = AsyncMock(return_value=None)
    service.embedding_cache.set = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock(return_value=None)
    return service


def _query_scopes_patch():
    return patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes")


@pytest.mark.asyncio
async def test_stale_cache_hit_falls_back_to_live_search():
    """None of the cached chunk_ids resolve (simulated re-ingest): the
    sub-query must not be silently dropped — a live search must run and its
    chunks must make it into the final result."""
    document_repository = MagicMock()
    # The cache's chunk_ids don't match anything in the repository anymore.
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=[])

    service = _build_service(document_repository)
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 8)
    service.result_cache.get = AsyncMock(
        return_value=CachedResult(
            chunk_ids=["stale-chunk-1", "stale-chunk-2"],
            scores=[0.9, 0.8],
            cached_at="2020-01-01T00:00:00+00:00",
            tenant_id="default",
        )
    )

    fresh_result = SearchResult(
        chunk_id="fresh-chunk-1",
        document_id="doc-1",
        tenant_id="default",
        score=0.95,
        metadata={"content": "fresh content after re-ingest"},
    )
    service.vector_searcher.search = AsyncMock(return_value=[fresh_result])

    with _query_scopes_patch() as mock_scopes:
        mock_scopes.return_value = QueryScopes(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
            shared_document_owner_tenants=[],
            group_ids=[],
            enforce_groups=False,
        )
        result = await service.retrieve(
            query="What is the timeout configuration for retries?",
            tenant_id="default",
        )

    service.vector_searcher.search.assert_called()
    assert any(c["chunk_id"] == "fresh-chunk-1" for c in result.chunks), (
        f"expected the live-search fallback chunk in the result, got: {result.chunks}"
    )


@pytest.mark.asyncio
async def test_valid_cache_hit_skips_live_search():
    """A cache hit that DOES resolve must keep using the cache — no
    embedding call, no vector search — exactly as before this fix."""
    document_repository = MagicMock()

    async def fake_get_chunks(chunk_ids):
        chunk_repo = {
            "chunk-1": SimpleNamespace(
                id="chunk-1", document_id="doc-1", content="cached content", metadata_={}
            )
        }
        return [chunk_repo[cid] for cid in chunk_ids if cid in chunk_repo]

    document_repository.get_chunks = AsyncMock(side_effect=fake_get_chunks)
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=[])

    service = _build_service(document_repository)

    async def _must_not_embed(*_a, **_kw):
        raise AssertionError("embedding must not be called on a resolved cache hit")

    service.embedding_service.embed_single = _must_not_embed
    service.result_cache.get = AsyncMock(
        return_value=CachedResult(
            chunk_ids=["chunk-1"],
            scores=[0.9],
            cached_at="2020-01-01T00:00:00+00:00",
            tenant_id="default",
        )
    )

    async def _must_not_search(*_a, **_kw):
        raise AssertionError("vector search must not run on a resolved cache hit")

    service.vector_searcher = SimpleNamespace(search=_must_not_search)

    with _query_scopes_patch() as mock_scopes:
        mock_scopes.return_value = QueryScopes(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
            shared_document_owner_tenants=[],
            group_ids=[],
            enforce_groups=False,
        )
        result = await service.retrieve(
            query="What is the timeout configuration for retries?",
            tenant_id="default",
        )

    assert any(c["chunk_id"] == "chunk-1" for c in result.chunks), (
        f"expected the cached chunk in the result, got: {result.chunks}"
    )
