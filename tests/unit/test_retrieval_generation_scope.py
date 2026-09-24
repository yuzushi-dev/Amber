from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from src.core.retrieval.application.retrieval_service import RetrievalService
from src.shared.kernel.models.query import QueryOptions
from src.core.retrieval.application.query.router import SearchMode
from src.core.retrieval.application.query.parser import QueryParser
from src.core.retrieval.domain.ports.vector_store_port import SearchResult


@pytest.mark.asyncio
@pytest.mark.parametrize("commercial", [True, False])
async def test_generation_selects_only_visible_commercial_documents(commercial):
    service = RetrievalService.__new__(RetrievalService)
    service.config = SimpleNamespace(top_k=5)
    service._get_effective_tenant_config = AsyncMock(return_value={})
    service._list_visible_document_ids = AsyncMock(return_value=["commercial", "ce", "unknown"])
    service.document_repository = SimpleNamespace(
        get_editions_by_ids=AsyncMock(return_value={
            "commercial": "commercial" if commercial else "unknown", "ce": "ce",
        }),
        list_visible_document_ids_by_taxonomy=AsyncMock(return_value=[]),
    )
    scopes = SimpleNamespace(
        effective_tenant_id="tenant", vector_scopes=["tenant"],
        graph_scopes=["tenant"], group_ids=["partner"], enforce_groups=True,
    )
    service.router = SimpleNamespace(route=AsyncMock(return_value=SearchMode.GLOBAL))
    service._resolve_vector_targets = AsyncMock(return_value=[])
    service._execute_vector_search = AsyncMock(return_value=SimpleNamespace(chunks=[
        SimpleNamespace(document_id="commercial"), SimpleNamespace(document_id="ce"),
        SimpleNamespace(document_id="unknown"), SimpleNamespace(document_id=None),
    ], trace=[]))
    service.circuit_breaker = MagicMock()
    result = await service.retrieve(
        "How do I hide View Mail?", "tenant", document_ids=["commercial", "ce", "unknown"],
        options=QueryOptions(search_mode=SearchMode.GLOBAL, use_sufficiency_loop=False),
        query_scopes=scopes, for_generation=True,
    )
    service._list_visible_document_ids.assert_awaited_once_with(
        viewer_tenant_id="tenant", owner_tenant_id="tenant",
        candidate_document_ids=ANY,
        group_ids=["partner"], enforce_groups=True,
    )
    assert set(service._list_visible_document_ids.await_args.kwargs["candidate_document_ids"]) == {
        "ce", "commercial", "unknown",
    }
    if commercial:
        assert service._execute_vector_search.await_args.kwargs["document_ids"] == ["commercial"]
        assert service.router.route.await_args.kwargs["explicit_mode"] == SearchMode.BASIC
        assert result.search_mode == SearchMode.BASIC.value
        assert [chunk.document_id for chunk in result.chunks] == ["commercial"]
    else:
        assert result.chunks == []
        service.router.route.assert_not_called()
        service._execute_vector_search.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [True, False])
async def test_document_scope_filters_cache_and_reranker(cached):
    service = RetrievalService.__new__(RetrievalService)
    service.sparse_embedding = None
    service.config = SimpleNamespace(
        enable_hybrid=False, initial_k=10, rerank_model="test", rerank_score_floor=None,
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
        get=AsyncMock(return_value=SimpleNamespace(
            chunk_ids=["commercial", "ce"], scores=[1.0, 1.0],
        ) if cached else None), set=AsyncMock(),
    )
    service._fetch_chunks_by_ids = AsyncMock(return_value=[
        {"document_id": doc, "chunk_id": doc, "content": doc + "_evidence", "score": 1.0}
        for doc in ("commercial", "ce")
    ])
    service._search_vector_targets = AsyncMock(return_value=([
        SearchResult(chunk_id=doc, document_id=doc, tenant_id="tenant", score=1.0,
                     metadata={"content": doc + "_evidence"})
        for doc in ("commercial", "ce")
    ], []))
    service.reranker = SimpleNamespace(rerank=AsyncMock(return_value=SimpleNamespace(
        results=[SimpleNamespace(index=0, score=1.0)],
    )))
    result = await service._execute_vector_search(
        structured_query=QueryParser.parse("View Mail"), tenant_id="tenant",
        document_ids=["commercial"], filters={}, top_k=5, trace=[], vector_targets=[],
        options=QueryOptions(use_hyde=False, use_decomposition=False),
    )
    assert [chunk["document_id"] for chunk in result.chunks] == ["commercial"]
    if cached:
        service.reranker.rerank.assert_not_called()
    else:
        assert service.reranker.rerank.await_args.kwargs["documents"] == ["commercial_evidence"]
