"""Global search must only surface communities backed by published chunks.

`_resolve_community_origins` is the only gate: a community that does not
resolve to an origin document (inactive, other tenant, or backed only by
unpublished chunks) is dropped before any LLM map call. These tests pin the
Cypher guards and the fail-closed behaviour around them; the Cypher semantics
themselves are exercised against a real Neo4j in
tests/graph_cypher/test_global_search_origins_cypher.py.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.retrieval.application.search.global_search import GlobalSearchService


def _report(chunk_id: str, score: float = 0.9):
    return SimpleNamespace(chunk_id=chunk_id, score=score, metadata={"content": f"report {chunk_id}"})


@pytest.fixture
def patched_llm_config(monkeypatch):
    from src.core.generation.application import llm_steps
    from src.shared.kernel import runtime

    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(llm_steps, "resolve_llm_step_config", lambda **_kwargs: SimpleNamespace())


def _service(reports, graph):
    vector_store = AsyncMock()
    vector_store.search.return_value = reports
    embedding_service = AsyncMock()
    embedding_service.embed_single.return_value = [0.1]
    service = GlobalSearchService(vector_store, AsyncMock(), embedding_service, neo4j_client=graph)
    service._map_report = AsyncMock(return_value="point")
    return service


def _mapped_reports(service) -> list[str]:
    return [call.args[1] for call in service._map_report.await_args_list]


@pytest.mark.asyncio
async def test_origin_query_filters_unpublished_chunks_inactive_communities_and_tenant():
    graph = AsyncMock()
    graph.execute_read.return_value = []
    service = GlobalSearchService(AsyncMock(), AsyncMock(), AsyncMock(), neo4j_client=graph)

    await service._resolve_community_origins(["com-1", "com-2"], "tenant-1")

    query, params = graph.execute_read.await_args.args
    assert "coalesce(c.is_published, true) = true" in query
    assert "coalesce(com.active, true) = true" in query
    assert "com.tenant_id = $tenant_id" in query
    assert "com.id IN $community_ids" in query
    assert params == {"community_ids": ["com-1", "com-2"], "tenant_id": "tenant-1"}


@pytest.mark.asyncio
async def test_communities_without_published_origin_are_dropped_before_mapping(patched_llm_config):
    # Neo4j returns no row for com-unpublished: all its backing chunks are unpublished.
    graph = AsyncMock()
    graph.execute_read.return_value = [{"community_id": "com-published", "primary_doc_id": "doc-1"}]
    service = _service([_report("com-unpublished"), _report("com-published")], graph)

    result = await service.search("query", "tenant-1")

    assert [c["chunk_id"] for c in result["candidates"]] == ["com-published"]
    assert result["candidates"][0]["document_id"] == "doc-1"
    assert _mapped_reports(service) == ["report com-published"]


@pytest.mark.asyncio
async def test_no_published_origin_for_any_community_returns_nothing(patched_llm_config):
    graph = AsyncMock()
    graph.execute_read.return_value = []
    service = _service([_report("com-1"), _report("com-2")], graph)

    assert await service.search("query", "tenant-1") == {"candidates": []}
    service._map_report.assert_not_awaited()


@pytest.mark.asyncio
async def test_origin_lookup_failure_fails_closed(patched_llm_config):
    graph = AsyncMock()
    graph.execute_read.side_effect = RuntimeError("neo4j down")
    service = _service([_report("com-1")], graph)

    assert await service.search("query", "tenant-1") == {"candidates": []}
    service._map_report.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_graph_client_fails_closed(patched_llm_config):
    service = _service([_report("com-1")], graph=None)

    assert await service.search("query", "tenant-1") == {"candidates": []}
    service._map_report.assert_not_awaited()


@pytest.mark.asyncio
async def test_rows_without_community_id_are_ignored(patched_llm_config):
    graph = AsyncMock()
    graph.execute_read.return_value = [
        {"community_id": None, "primary_doc_id": "doc-orphan"},
        {"primary_doc_id": "doc-no-key"},
    ]
    service = _service([_report("com-1")], graph)

    assert await service.search("query", "tenant-1") == {"candidates": []}
    service._map_report.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("allowed_doc_ids", "expected"),
    [
        (None, ["com-a", "com-b"]),
        (["doc-a"], ["com-a"]),
        ([], []),
    ],
)
async def test_allowed_doc_ids_applies_on_top_of_published_filter(
    patched_llm_config, allowed_doc_ids, expected
):
    graph = AsyncMock()
    graph.execute_read.return_value = [
        {"community_id": "com-a", "primary_doc_id": "doc-a"},
        {"community_id": "com-b", "primary_doc_id": "doc-b"},
    ]
    service = _service([_report("com-a"), _report("com-b"), _report("com-unpublished")], graph)

    result = await service.search("query", "tenant-1", allowed_doc_ids=allowed_doc_ids)

    assert [c["chunk_id"] for c in result["candidates"]] == expected
    assert "com-unpublished" not in [c["chunk_id"] for c in result["candidates"]]
