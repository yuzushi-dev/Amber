import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.retrieval.application.search.graph_traversal import GraphTraversalService


def test_beam_search_basic():
    """Verify that beam search executes cypher and returns candidates."""
    mock_neo4j = MagicMock(spec=Neo4jClient)
    mock_neo4j.execute_read = AsyncMock(return_value=[
        {"chunk_id": "c1", "content": "Content 1", "document_id": "d1"},
        {"chunk_id": "c2", "content": "Content 2", "document_id": "d1"}
    ])

    service = GraphTraversalService(mock_neo4j)
    results = asyncio.run(service.beam_search(
        seed_entity_ids=["e1"],
        tenant_id="test",
        depth=1,
        beam_width=2
    ))

    assert len(results) == 2
    assert results[0].chunk_id == "c1"
    assert results[0].source == "graph"

    # Verify the call to neo4j
    mock_neo4j.execute_read.assert_called_once()
    args, kwargs = mock_neo4j.execute_read.call_args
    assert "seed_ids" in args[1]
    assert args[1]["seed_ids"] == ["e1"]

def test_beam_search_empty():
    """Verify empty results for empty seeds."""
    mock_neo4j = MagicMock(spec=Neo4jClient)
    service = GraphTraversalService(mock_neo4j)
    results = asyncio.run(service.beam_search([], "test"))
    assert results == []
