import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.retrieval.application.retrieval_service import RetrievalResult, RetrievalService


@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_basic_search_orchestration(mock_rc, mock_sc, mock_builder):
    """Verify that RetrievalService correctly orchestrates basic vector search."""
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )

    # Mock searchers
    service.vector_searcher.search = AsyncMock(return_value=[])
    # Fix: Also mock the underlying vector_store.search since the fallback mechanism calls it directly
    service.vector_store.search = AsyncMock(return_value=[])

    service.entity_searcher.search = AsyncMock(return_value=[])
    service.graph_searcher.search_by_entities = AsyncMock(return_value=[])
    service.graph_traversal.beam_search = AsyncMock(return_value=[])

    # Mock result cache (needs to be async)
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock()

    # Mock embedding
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1]*1536)

    # Mock router to return BASIC
    service.router.route = AsyncMock(return_value="basic")

    # Use a dict for options to avoid pydantic issues in mock env
    options = MagicMock()
    options.search_mode = "basic"
    options.use_rewrite = False
    options.use_decomposition = False
    options.use_hyde = False

    result = asyncio.run(service.retrieve("test query", tenant_id="test", options=options))

    assert isinstance(result, RetrievalResult)
    service.vector_searcher.search.assert_called_once()
    # Entity search is currently disabled in BASIC mode
    # service.entity_searcher.search.assert_called_once()

@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_global_search_orchestration(mock_rc, mock_sc, mock_builder):
    """Verify Global Search mode is called."""
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )
    service.global_search.search = AsyncMock(return_value={"answer": "Global Answer", "sources": ["s1"]})
    service.router.route = AsyncMock(return_value="global") # Mode.GLOBAL

    options = MagicMock()
    options.search_mode = "global"
    options.use_rewrite = False

    result = asyncio.run(service.retrieve("global query", tenant_id="test", options=options))

    assert result.chunks[0]["content"] == "Global Answer"
    service.global_search.search.assert_called_once()

@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_drift_search_orchestration(mock_rc, mock_sc, mock_builder):
    """Verify DRIFT Search mode is called."""
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )
    service.drift_search.search = AsyncMock(return_value={"candidates": [], "follow_ups": [], "answer": "Drift"})
    service.router.route = AsyncMock(return_value="drift") # Mode.DRIFT

    options = MagicMock()
    options.search_mode = "drift"
    options.use_rewrite = False

    asyncio.run(service.retrieve("drift query", tenant_id="test", options=options))

    service.drift_search.search.assert_called_once()


@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_retrieval_uses_active_collection(mock_rc, mock_sc, mock_builder):
    """Verify retrieval uses the tenant active collection name when configured."""
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])

    class StubTuning:
        async def get_tenant_config(self, tenant_id: str):
            return {"active_vector_collection": "amber_custom"}

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
        tuning_service=StubTuning(),
    )

    service.vector_searcher.search = AsyncMock(return_value=[])
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock()
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 1536)
    service.router.route = AsyncMock(return_value="basic")

    options = MagicMock()
    options.search_mode = "basic"
    options.use_rewrite = False
    options.use_decomposition = False
    options.use_hyde = False

    asyncio.run(service.retrieve("test query", tenant_id="tenant-1", options=options))

    _, kwargs = service.vector_searcher.search.call_args
    assert kwargs["collection_name"] == "amber_custom"
