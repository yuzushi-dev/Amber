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
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 1536)

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
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )
    service.global_search.search = AsyncMock(
        return_value={
            "candidates": [
                {
                    "chunk_id": "community-1",
                    "document_id": "doc-1",
                    "content": "Global Answer",
                    "score": 1.0,
                }
            ]
        }
    )
    service.router.route = AsyncMock(return_value="global")  # Mode.GLOBAL

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
    service.drift_search.search = AsyncMock(
        return_value={"candidates": [], "follow_ups": [], "answer": "Drift"}
    )
    service.router.route = AsyncMock(return_value="drift")  # Mode.DRIFT

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



@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_retrieval_searches_shared_default_scope_with_acl_filters(
    mock_rc, mock_sc, mock_builder
):
    """Verify non-default retrieval searches shared default docs with document ACL filters."""
    from unittest.mock import call

    from src.core.retrieval.domain.candidate import Candidate
    from src.core.tenants.application.query_scopes import QueryScopes

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=["default-doc-1"])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )

    service.vector_searcher.search = AsyncMock(
        side_effect=[
            [
                Candidate(
                    chunk_id="shared-chunk-1",
                    document_id="default-doc-1",
                    tenant_id="default",
                    content="Shared Carbonio content",
                    score=0.92,
                    metadata={"content": "Shared Carbonio content"},
                )
            ],
            [
                Candidate(
                    chunk_id="local-chunk-1",
                    document_id="local-doc-1",
                    tenant_id="engineering",
                    content="Local engineering notes",
                    score=0.81,
                    metadata={"content": "Local engineering notes"},
                )
            ],
        ]
    )
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock()
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 1536)
    service.router.route = AsyncMock(return_value="basic")
    service.reranker = None

    options = MagicMock()
    options.search_mode = "basic"
    options.use_rewrite = False
    options.use_decomposition = False
    options.use_hyde = False

    result = asyncio.run(
        service.retrieve(
            "How do I configure Carbonio?",
            tenant_id="engineering",
            options=options,
            query_scopes=QueryScopes(
                effective_tenant_id="engineering",
                vector_scopes=["default", "engineering"],
                graph_scopes=["default", "engineering"],
                shared_document_owner_tenants=["default"],
            ),
        )
    )

    assert [chunk["chunk_id"] for chunk in result.chunks] == [
        "shared-chunk-1",
        "local-chunk-1",
    ]
    document_repository.list_visible_document_ids.assert_awaited_once_with(
        viewer_tenant_id="engineering",
        owner_tenant_id="default",
        candidate_document_ids=None,
    )
    service.vector_searcher.search.assert_has_calls(
        [
            call(
                query_vector=[0.1] * 1536,
                tenant_id="default",
                document_ids=["default-doc-1"],
                limit=10,
                score_threshold=None,
                filters={},
                collection_name="document_chunks",
            ),
            call(
                query_vector=[0.1] * 1536,
                tenant_id="engineering",
                document_ids=None,
                limit=10,
                score_threshold=None,
                filters={},
                collection_name="amber_engineering",
            ),
        ]
    )



@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_global_search_uses_default_graph_scope_with_acl_filters(
    mock_rc, mock_sc, mock_builder
):
    from unittest.mock import call

    from src.core.tenants.application.query_scopes import QueryScopes

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=["default-doc-1"])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )
    service.global_search.search = AsyncMock(
        side_effect=[
            {
                "candidates": [
                    {
                        "chunk_id": "community-default",
                        "document_id": "default-doc-1",
                        "content": "Shared default community",
                        "score": 1.0,
                    }
                ]
            },
            {
                "candidates": [
                    {
                        "chunk_id": "community-local",
                        "document_id": "local-doc-1",
                        "content": "Local engineering community",
                        "score": 0.7,
                    }
                ]
            },
        ]
    )
    service.router.route = AsyncMock(return_value="global")

    options = MagicMock()
    options.search_mode = "global"
    options.use_rewrite = False

    result = asyncio.run(
        service.retrieve(
            "global query",
            tenant_id="engineering",
            options=options,
            query_scopes=QueryScopes(
                effective_tenant_id="engineering",
                vector_scopes=["default", "engineering"],
                graph_scopes=["default", "engineering"],
                shared_document_owner_tenants=["default"],
            ),
        )
    )

    assert [chunk["chunk_id"] for chunk in result.chunks] == [
        "community-default",
        "community-local",
    ]
    document_repository.list_visible_document_ids.assert_awaited_once_with(
        viewer_tenant_id="engineering",
        owner_tenant_id="default",
        candidate_document_ids=None,
    )
    service.global_search.search.assert_has_calls(
        [
            call(
                query="global query",
                tenant_id="default",
                tenant_config={},
                allowed_doc_ids=["default-doc-1"],
            ),
            call(
                query="global query",
                tenant_id="engineering",
                tenant_config={},
                allowed_doc_ids=None,
            ),
        ]
    )



@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_retrieval_skips_shared_default_scope_when_vector_acl_flag_disabled(
    mock_rc, mock_sc, mock_builder, monkeypatch
):
    from src.core.retrieval.domain.candidate import Candidate
    from src.core.tenants.application.query_scopes import QueryScopes

    monkeypatch.setattr(
        "src.core.retrieval.application.retrieval_service.settings.enable_acl_aware_vector_retrieval",
        False,
    )

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=["default-doc-1"])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )
    service.vector_searcher.search = AsyncMock(
        return_value=[
            Candidate(
                chunk_id="local-chunk-1",
                document_id="local-doc-1",
                tenant_id="engineering",
                content="Local engineering notes",
                score=0.81,
                metadata={"content": "Local engineering notes"},
            )
        ]
    )
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock()
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 1536)
    service.router.route = AsyncMock(return_value="basic")
    service.reranker = None

    options = MagicMock()
    options.search_mode = "basic"
    options.use_rewrite = False
    options.use_decomposition = False
    options.use_hyde = False

    result = asyncio.run(
        service.retrieve(
            "How do I configure Carbonio?",
            tenant_id="engineering",
            options=options,
            query_scopes=QueryScopes(
                effective_tenant_id="engineering",
                vector_scopes=["default", "engineering"],
                graph_scopes=["default", "engineering"],
                shared_document_owner_tenants=["default"],
            ),
        )
    )

    assert [chunk["chunk_id"] for chunk in result.chunks] == ["local-chunk-1"]
    assert document_repository.list_visible_document_ids.await_count == 0
    _, kwargs = service.vector_searcher.search.call_args
    assert kwargs["tenant_id"] == "engineering"
    assert kwargs["document_ids"] is None


@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_global_search_skips_shared_default_scope_when_graph_acl_flag_disabled(
    mock_rc, mock_sc, mock_builder, monkeypatch
):
    from src.core.tenants.application.query_scopes import QueryScopes

    monkeypatch.setattr(
        "src.core.retrieval.application.retrieval_service.settings.enable_acl_aware_graph_retrieval",
        False,
    )

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=["default-doc-1"])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )
    service.global_search.search = AsyncMock(
        return_value={
            "candidates": [
                {
                    "chunk_id": "community-local",
                    "document_id": "local-doc-1",
                    "content": "Local engineering community",
                    "score": 0.7,
                }
            ]
        }
    )
    service.router.route = AsyncMock(return_value="global")

    options = MagicMock()
    options.search_mode = "global"
    options.use_rewrite = False

    result = asyncio.run(
        service.retrieve(
            "global query",
            tenant_id="engineering",
            options=options,
            query_scopes=QueryScopes(
                effective_tenant_id="engineering",
                vector_scopes=["default", "engineering"],
                graph_scopes=["default", "engineering"],
                shared_document_owner_tenants=["default"],
            ),
        )
    )

    assert [chunk["chunk_id"] for chunk in result.chunks] == ["community-local"]
    assert document_repository.list_visible_document_ids.await_count == 0
    _, kwargs = service.global_search.search.call_args
    assert kwargs["tenant_id"] == "engineering"
    assert kwargs["allowed_doc_ids"] is None


@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_retrieval_skips_default_scope_when_no_shared_docs_are_visible(
    mock_rc, mock_sc, mock_builder
):
    from src.core.retrieval.domain.candidate import Candidate
    from src.core.tenants.application.query_scopes import QueryScopes

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )

    service.vector_searcher.search = AsyncMock(
        return_value=[
            Candidate(
                chunk_id="local-chunk-1",
                document_id="local-doc-1",
                tenant_id="engineering",
                content="Local engineering notes",
                score=0.81,
                metadata={"content": "Local engineering notes"},
            )
        ]
    )
    service.result_cache.get = AsyncMock(return_value=None)
    service.result_cache.set = AsyncMock()
    service.embedding_service.embed_single = AsyncMock(return_value=[0.1] * 1536)
    service.router.route = AsyncMock(return_value="basic")
    service.reranker = None

    options = MagicMock()
    options.search_mode = "basic"
    options.use_rewrite = False
    options.use_decomposition = False
    options.use_hyde = False

    result = asyncio.run(
        service.retrieve(
            "How do I configure Carbonio?",
            tenant_id="engineering",
            options=options,
            query_scopes=QueryScopes(
                effective_tenant_id="engineering",
                vector_scopes=["default", "engineering"],
                graph_scopes=["default", "engineering"],
                shared_document_owner_tenants=["default"],
            ),
        )
    )

    assert [chunk["chunk_id"] for chunk in result.chunks] == ["local-chunk-1"]
    document_repository.list_visible_document_ids.assert_awaited_once_with(
        viewer_tenant_id="engineering",
        owner_tenant_id="default",
        candidate_document_ids=None,
    )
    _, kwargs = service.vector_searcher.search.call_args
    assert kwargs["tenant_id"] == "engineering"
    assert kwargs["document_ids"] is None


@patch("src.core.generation.domain.ports.provider_factory._provider_factory_builder")
@patch("src.core.retrieval.application.retrieval_service.SemanticCache")
@patch("src.core.retrieval.application.retrieval_service.ResultCache")
def test_global_search_skips_default_scope_when_no_shared_docs_are_visible(
    mock_rc, mock_sc, mock_builder
):
    from src.core.tenants.application.query_scopes import QueryScopes

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])
    vector_store.hybrid_search = AsyncMock(return_value=[])
    graph_store = MagicMock()
    document_repository = MagicMock()
    document_repository.get_chunks = AsyncMock(return_value=[])
    document_repository.list_visible_document_ids = AsyncMock(return_value=[])

    service = RetrievalService(
        document_repository=document_repository,
        vector_store=vector_store,
        neo4j_client=graph_store,
        openai_api_key="sk-test",
    )
    service.global_search.search = AsyncMock(
        return_value={
            "candidates": [
                {
                    "chunk_id": "community-local",
                    "document_id": "local-doc-1",
                    "content": "Local engineering community",
                    "score": 0.7,
                }
            ]
        }
    )
    service.router.route = AsyncMock(return_value="global")

    options = MagicMock()
    options.search_mode = "global"
    options.use_rewrite = False

    result = asyncio.run(
        service.retrieve(
            "global query",
            tenant_id="engineering",
            options=options,
            query_scopes=QueryScopes(
                effective_tenant_id="engineering",
                vector_scopes=["default", "engineering"],
                graph_scopes=["default", "engineering"],
                shared_document_owner_tenants=["default"],
            ),
        )
    )

    assert [chunk["chunk_id"] for chunk in result.chunks] == ["community-local"]
    document_repository.list_visible_document_ids.assert_awaited_once_with(
        viewer_tenant_id="engineering",
        owner_tenant_id="default",
        candidate_document_ids=None,
    )
    _, kwargs = service.global_search.search.call_args
    assert kwargs["tenant_id"] == "engineering"
    assert kwargs["allowed_doc_ids"] is None
