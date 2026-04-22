"""
Integration tests for taxonomy-aware retrieval routing.

These tests verify that the taxonomy resolver and document ID filtering
are correctly wired into the retrieval pipeline.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application.retrieval_service import RetrievalService


def _make_service(visible_ids_by_taxonomy=None):
    """Build a RetrievalService with mocked dependencies."""
    vector_store = MagicMock()
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids_by_taxonomy = AsyncMock(
        return_value=visible_ids_by_taxonomy or []
    )

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
    service.entity_searcher.search = AsyncMock(return_value=[])
    service.graph_searcher.search_by_entities = AsyncMock(return_value=[])
    service.graph_traversal.beam_search = AsyncMock(return_value=[])
    service.reranker = None
    # Async-mock the cache so retrieve() doesn't fail on await
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock(return_value=None)
    service.embedding_cache.get = AsyncMock(return_value=None)
    service.embedding_cache.set = AsyncMock(return_value=None)

    return service


@pytest.mark.asyncio
async def test_admin_query_calls_taxonomy_filter_with_admin():
    """An admin query triggers list_visible_document_ids_by_taxonomy with audience=admin."""
    service = _make_service(visible_ids_by_taxonomy=["doc-admin-1"])

    with (
        patch("src.core.retrieval.application.retrieval_service.fuse_results", return_value=[]),
        patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes") as mock_scopes,
    ):
        mock_scopes.return_value = MagicMock(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
        )
        await service.retrieve(
            query="How do delegate admins work?",
            tenant_id="default",
            include_trace=True,
        )

    service.document_repository.list_visible_document_ids_by_taxonomy.assert_called()
    call_kwargs = service.document_repository.list_visible_document_ids_by_taxonomy.call_args
    assert call_kwargs.kwargs.get("audience") == "admin" or \
           (call_kwargs.args and "admin" in str(call_kwargs.args))


@pytest.mark.asyncio
async def test_ce_query_calls_taxonomy_filter_with_ce_edition():
    """A CE-explicit query triggers taxonomy filter with edition=ce."""
    service = _make_service(visible_ids_by_taxonomy=["doc-ce-1"])

    with (
        patch("src.core.retrieval.application.retrieval_service.fuse_results", return_value=[]),
        patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes") as mock_scopes,
    ):
        mock_scopes.return_value = MagicMock(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
        )
        await service.retrieve(
            query="How do delegate admins work in CE?",
            tenant_id="default",
            include_trace=True,
        )

    service.document_repository.list_visible_document_ids_by_taxonomy.assert_called()
    call_kwargs = service.document_repository.list_visible_document_ids_by_taxonomy.call_args
    assert call_kwargs.kwargs.get("edition") == "ce" or \
           (call_kwargs.args and "ce" in str(call_kwargs.args))


@pytest.mark.asyncio
async def test_taxonomy_trace_step_is_added():
    """Taxonomy resolution step appears in the trace when include_trace=True."""
    service = _make_service(visible_ids_by_taxonomy=["doc-1"])

    with (
        patch("src.core.retrieval.application.retrieval_service.fuse_results", return_value=[]),
        patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes") as mock_scopes,
    ):
        mock_scopes.return_value = MagicMock(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
        )
        result = await service.retrieve(
            query="How do I configure a domain?",
            tenant_id="default",
            include_trace=True,
        )

    trace_steps = [s.get("step") for s in result.trace]
    assert "taxonomy_routing" in trace_steps


@pytest.mark.asyncio
async def test_broadening_happens_when_strict_returns_empty():
    """When strict taxonomy filter returns empty, broadening is attempted."""
    call_count = {"n": 0}
    original_side_effect = [
        [],           # strict: edition + audience -> empty
        ["doc-ce-1"], # broadened: edition only -> returns result
    ]

    async def side_effect(**kwargs):
        n = call_count["n"]
        call_count["n"] += 1
        return original_side_effect[n] if n < len(original_side_effect) else []

    service = _make_service()
    service.document_repository.list_visible_document_ids_by_taxonomy = AsyncMock(
        side_effect=side_effect
    )

    with (
        patch("src.core.retrieval.application.retrieval_service.fuse_results", return_value=[]),
        patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes") as mock_scopes,
    ):
        mock_scopes.return_value = MagicMock(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
        )
        await service.retrieve(
            query="How do delegate admins work?",
            tenant_id="default",
        )

    # Should have been called at least twice (strict + broadened)
    assert service.document_repository.list_visible_document_ids_by_taxonomy.call_count >= 2


@pytest.mark.asyncio
async def test_explicit_filter_overrides_inferred_context():
    """When filters.edition is set explicitly, it overrides query inference."""
    service = _make_service(visible_ids_by_taxonomy=["doc-ce-2"])

    with (
        patch("src.core.retrieval.application.retrieval_service.fuse_results", return_value=[]),
        patch("src.core.retrieval.application.retrieval_service.resolve_query_scopes") as mock_scopes,
    ):
        mock_scopes.return_value = MagicMock(
            effective_tenant_id="default",
            vector_scopes=["default"],
            graph_scopes=["default"],
        )
        # Query sounds commercial, but explicit override says ce
        await service.retrieve(
            query="How do delegate admins work?",
            tenant_id="default",
            filters={"edition": "ce"},
        )

    call_kwargs = service.document_repository.list_visible_document_ids_by_taxonomy.call_args
    assert call_kwargs.kwargs.get("edition") == "ce"
