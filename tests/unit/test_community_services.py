import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.graph.application.communities.lifecycle import CommunityLifecycleManager
from src.core.graph.application.communities.summarizer import CommunitySummarizer


@pytest.fixture
def mock_neo4j():
    return AsyncMock()


@pytest.fixture
def mock_factory():
    factory = MagicMock()
    factory.get_llm_provider.return_value = AsyncMock()
    return factory


@pytest.fixture
def mock_embedding_service():
    service = AsyncMock()
    service.embed_single.return_value = [0.1] * 1536
    return service


class TestCommunitySummarizer:
    @pytest.mark.asyncio
    async def test_summarize_community_success(self, mock_neo4j, mock_factory):
        # Setup
        summarizer = CommunitySummarizer(mock_neo4j, mock_factory)

        # Mock data fetch
        mock_neo4j.execute_read.side_effect = [
            [{"name": "Entity A", "type": "Person", "description": "Desc A"}],  # entities
            [
                {
                    "source": "Entity A",
                    "target": "Entity B",
                    "type": "WORKS_WITH",
                    "description": "Rel Desc",
                }
            ],  # relationships
            [],  # child summaries
            [{"id": "chunk_1", "content": "Sample text unit content"}],  # text_units
        ]

        # Mock LLM response
        llm_result = MagicMock()
        llm_result.text = json.dumps(
            {
                "title": "Test Community",
                "summary": "This is a test summary.",
                "rating": 8,
                "key_entities": ["Entity A"],
                "findings": ["Finding 1"],
            }
        )
        mock_factory.get_llm_provider.return_value.generate.return_value = llm_result

        # Execute
        with patch("src.shared.kernel.runtime.get_settings"):
            result = await summarizer.summarize_community("comm_0_123", "tenant_1")

        # Verify
        assert result["title"] == "Test Community"
        assert mock_neo4j.execute_write.called
        assert "SET c.title = $title" in mock_neo4j.execute_write.call_args[0][0]

    @pytest.mark.asyncio
    async def test_summarize_community_no_data(self, mock_neo4j, mock_factory):
        summarizer = CommunitySummarizer(mock_neo4j, mock_factory)
        mock_neo4j.execute_read.return_value = []

        with patch("src.shared.kernel.runtime.get_settings"):
            result = await summarizer.summarize_community("comm_0_empty", "tenant_1")
        assert result == {}


class TestCommunityLifecycle:
    @pytest.mark.asyncio
    async def test_mark_stale_by_entities(self, mock_neo4j):
        manager = CommunityLifecycleManager(mock_neo4j)
        mock_neo4j.execute_write.return_value = [{"count": 2}]

        await manager.mark_stale_by_entities(["EntityA", "EntityB"], "tenant_1")

        assert mock_neo4j.execute_write.called
        query = mock_neo4j.execute_write.call_args[0][0]
        assert "WHERE e.name IN $names" in query

    @pytest.mark.asyncio
    async def test_cleanup_orphans(self, mock_neo4j):
        manager = CommunityLifecycleManager(mock_neo4j)
        mock_neo4j.execute_read.return_value = [{"name": "OrphanEntity"}]

        await manager.cleanup_orphans("tenant_1")

        assert mock_neo4j.execute_read.called
        query = mock_neo4j.execute_read.call_args[0][0]
        assert "RETURN e.name as name" in query
        # Check that it tried to create misc community and link orphans
        assert mock_neo4j.execute_write.call_count == 2
        link_query = mock_neo4j.execute_write.call_args[0][0]
        assert "e.name IN $entity_names" in link_query
