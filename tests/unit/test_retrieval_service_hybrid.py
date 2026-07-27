"""Tests for the retrieval service — taxonomy routing (formerly contained
_execute_hybrid_search tests which were removed along with that dead method).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application.retrieval_service import RetrievalService

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
