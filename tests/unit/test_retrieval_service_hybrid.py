from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application.query.models import StructuredQuery
from src.core.retrieval.application.retrieval_service import RetrievalResult, RetrievalService
from src.shared.kernel.models.query import QueryOptions, SearchMode


@pytest.mark.asyncio
async def test_hybrid_search_uses_tenant_weights():
    """Verify hybrid path forwards tenant weights into adaptive fusion."""
    vector_store = MagicMock()
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])

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

    structured_query = StructuredQuery(original_query="q", cleaned_query="q")
    options = QueryOptions(search_mode=SearchMode.BASIC)
    trace: list[dict] = []

    with (
        patch(
            "src.core.retrieval.application.retrieval_service.get_adaptive_weights",
            return_value={"vector": 0.7, "graph": 0.3},
        ) as mock_weights,
        patch("src.core.retrieval.application.retrieval_service.fuse_results", return_value=[]),
    ):
        result = await service._execute_hybrid_search(
            structured_query=structured_query,
            tenant_id="tenant-1",
            document_ids=None,
            filters={},
            top_k=5,
            options=options,
            trace=trace,
            collection_name="amber_tenant_1",
            tenant_config={"weights": {"vector": 0.9, "graph": 0.1}},
        )

    assert isinstance(result, RetrievalResult)
    assert result.chunks == []
    mock_weights.assert_called_once_with(
        query_type=options.search_mode,
        tenant_config={"vector": 0.9, "graph": 0.1},
    )
