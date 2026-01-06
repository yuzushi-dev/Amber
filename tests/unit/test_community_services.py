import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from src.core.graph.communities.summarizer import CommunitySummarizer
from src.core.graph.communities.embeddings import CommunityEmbeddingService
from src.core.graph.communities.lifecycle import CommunityLifecycleManager

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
            [{"name": "Entity A", "type": "Person", "description": "Desc A"}], # entities
            [{"source": "Entity A", "target": "Entity B", "type": "WORKS_WITH", "description": "Rel Desc"}], # relationships
            [],  # child summaries
            [{"id": "chunk_1", "content": "Sample text unit content"}]  # text_units
        ]
        
        # Mock LLM response
        llm_result = MagicMock()
        llm_result.text = json.dumps({
            "title": "Test Community",
            "summary": "This is a test summary.",
            "rating": 8,
            "key_entities": ["Entity A"],
            "findings": ["Finding 1"]
        })
        mock_factory.get_llm_provider.return_value.generate.return_value = llm_result
        
        # Execute
        result = await summarizer.summarize_community("comm_0_123", "tenant_1")
        
        # Verify
        assert result["title"] == "Test Community"
        assert mock_neo4j.execute_write.called
        assert "SET c.title = $title" in mock_neo4j.execute_write.call_args[0][0]

    @pytest.mark.asyncio
    async def test_summarize_community_no_data(self, mock_neo4j, mock_factory):
        summarizer = CommunitySummarizer(mock_neo4j, mock_factory)
        mock_neo4j.execute_read.return_value = []
        
        result = await summarizer.summarize_community("comm_0_empty", "tenant_1")
        assert result == {}

class TestCommunityEmbeddingService:
    @pytest.mark.asyncio
    async def test_embed_and_store(self, mock_embedding_service):
        with patch("src.core.graph.communities.embeddings._get_milvus") as mock_milvus_pkg:
            # Setup Milvus mocks
            mock_collection = MagicMock()
            mock_milvus_pkg.return_value = {
                "connections": MagicMock(),
                "utility": MagicMock(),
                "Collection": MagicMock(return_value=mock_collection),
                "FieldSchema": MagicMock(),
                "DataType": MagicMock(),
                "CollectionSchema": MagicMock()
            }
            mock_milvus_pkg.return_value["utility"].has_collection.return_value = True

            service = CommunityEmbeddingService(mock_embedding_service)
            
            data = {
                "id": "comm_0_123",
                "tenant_id": "tenant_1",
                "level": 0,
                "title": "Test",
                "summary": "Summary"
            }
            
            await service.embed_and_store_community(data)
            
            assert mock_embedding_service.embed_single.called
            assert mock_collection.upsert.called

class TestCommunityLifecycle:
    @pytest.mark.asyncio
    async def test_mark_stale_by_entities(self, mock_neo4j):
        manager = CommunityLifecycleManager(mock_neo4j)
        mock_neo4j.execute_write.return_value = [{"count": 2}]
        
        await manager.mark_stale_by_entities(["ent_1", "ent_2"])
        
        assert mock_neo4j.execute_write.called
        assert "WHERE e.id IN $entity_ids" in mock_neo4j.execute_write.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cleanup_orphans(self, mock_neo4j):
        manager = CommunityLifecycleManager(mock_neo4j)
        mock_neo4j.execute_read.return_value = [{"id": "ent_orph"}]
        
        await manager.cleanup_orphans("tenant_1")
        
        assert mock_neo4j.execute_read.called
        # Check that it tried to create misc community and link orphans
        assert mock_neo4j.execute_write.call_count == 2
