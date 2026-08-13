from unittest.mock import AsyncMock

import pytest

from src.core.graph.application.communities.leiden import CommunityDetector


@pytest.mark.asyncio
async def test_detection_stages_a_generation_without_cleaning_active_communities():
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
    assert result["status"] == "success"
    assert result["generation_id"]
    query, params = graph.execute_write.await_args.args
    assert "active = false" in query
    assert params["generation_id"] == result["generation_id"]


@pytest.mark.asyncio
async def test_activation_is_tenant_scoped_and_deletes_old_generation_after_publish():
    graph = AsyncMock()
    detector = CommunityDetector(graph)

    await detector.activate_generation("tenant-1", "generation-1")

    query, params = graph.execute_write.await_args.args
    assert "new.tenant_id = $tenant_id" in query
    assert "new.generation_id = $generation_id" in query
    assert "old.generation_id <> $generation_id" in query
    assert "DETACH DELETE old" in query
    assert params == {"tenant_id": "tenant-1", "generation_id": "generation-1"}


@pytest.mark.asyncio
async def test_discard_generation_is_tenant_scoped():
    graph = AsyncMock()
    detector = CommunityDetector(graph)

    await detector.discard_generation("tenant-1", "generation-1")

    query, params = graph.execute_write.await_args.args
    assert "c.tenant_id = $tenant_id" in query
    assert "c.generation_id = $generation_id" in query
    assert "DETACH DELETE c" in query
    assert params == {"tenant_id": "tenant-1", "generation_id": "generation-1"}
