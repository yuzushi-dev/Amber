from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.graph.application.communities.leiden import CommunityDetector
from src.core.graph.application.communities.summarizer import CommunitySummarizer
from src.core.retrieval.application.search.global_search import GlobalSearchService


@pytest.mark.asyncio
async def test_detection_stages_without_cleaning_active_communities():
    graph = AsyncMock()
    graph.execute_read.return_value = [{"community_count": 1, "invalid_links": 0}]
    detector = CommunityDetector(graph)
    detector._cleanup_old_communities = AsyncMock()
    detector._fetch_l0_graph = AsyncMock(return_value=(["entity-1"], []))
    detector._run_hierarchical_leiden = lambda *_args: [
        {
            "id": "community-1",
            "level": 0,
            "title": "Community 0.0",
            "members": ["entity-1"],
            "child_communities": [],
        }
    ]

    result = await detector.detect_communities("tenant-1")

    detector._cleanup_old_communities.assert_not_awaited()
    assert result["generation_id"]
    query, params = graph.execute_write.await_args.args
    assert "comm.active = false" in query
    assert params["generation_id"] == result["generation_id"]


@pytest.mark.asyncio
async def test_activation_swaps_visibility_without_deleting_previous_generation():
    graph = AsyncMock()
    graph.execute_write.return_value = [{"activated": 1}]
    detector = CommunityDetector(graph)

    await detector.activate_generation("tenant-1", "generation-1")

    query, params = graph.execute_write.await_args.args
    assert "new.active = true" in query
    assert "old.active = false" in query
    assert "DELETE" not in query
    assert params == {"tenant_id": "tenant-1", "generation_id": "generation-1"}


@pytest.mark.asyncio
async def test_discard_generation_is_tenant_scoped():
    graph = AsyncMock()
    detector = CommunityDetector(graph)

    await detector.discard_generation("tenant-1", "generation-1")

    query, params = graph.execute_write.await_args.args
    assert "c.tenant_id = $tenant_id" in query
    assert "c.generation_id = $generation_id" in query
    assert params == {"tenant_id": "tenant-1", "generation_id": "generation-1"}


@pytest.mark.asyncio
async def test_summarizer_selects_only_requested_staging_generation():
    graph = AsyncMock()
    graph.execute_read.return_value = []
    summarizer = CommunitySummarizer(graph, AsyncMock())

    await summarizer.summarize_all_stale("tenant-1", generation_id="generation-1")

    query, params = graph.execute_read.await_args.args
    assert "c.generation_id = $generation_id" in query
    assert params["generation_id"] == "generation-1"


@pytest.mark.asyncio
async def test_global_search_resolves_only_active_communities():
    graph = AsyncMock()
    graph.execute_read.return_value = []
    service = GlobalSearchService(AsyncMock(), AsyncMock(), AsyncMock(), neo4j_client=graph)

    await service._resolve_community_origins(["community-1"], "tenant-1")

    query, _params = graph.execute_read.await_args.args
    assert "coalesce(com.active, true) = true" in query


@pytest.mark.asyncio
async def test_global_search_drops_inactive_vectors_before_llm_mapping(monkeypatch):
    from src.core.generation.application import llm_steps
    from src.shared.kernel import runtime

    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        llm_steps,
        "resolve_llm_step_config",
        lambda **_kwargs: SimpleNamespace(),
    )
    vector_store = AsyncMock()
    vector_store.search.return_value = [
        SimpleNamespace(chunk_id="inactive-community", metadata={"content": "old"})
    ]
    embedding_service = AsyncMock()
    embedding_service.embed_single.return_value = [0.1]
    service = GlobalSearchService(vector_store, AsyncMock(), embedding_service)
    service._resolve_community_origins = AsyncMock(return_value={})
    service._map_report = AsyncMock(return_value="point")

    result = await service.search("query", "tenant-1")

    assert result == {"candidates": []}
    service._map_report.assert_not_awaited()
