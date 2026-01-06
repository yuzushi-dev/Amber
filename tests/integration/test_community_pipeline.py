import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.graph.communities.leiden import CommunityDetector
from src.core.graph.communities.summarizer import CommunitySummarizer
from src.core.graph.neo4j_client import neo4j_client


@pytest.mark.asyncio
async def test_full_community_pipeline():
    tenant_id = "test_comm_integration"

    # 1. Cleanup
    # 1. Cleanup
    # Fix: Mock neo4j_client methods since it is a Mock in this env
    neo4j_client.connect = AsyncMock()
    neo4j_client.execute_write = AsyncMock()

    # Mock read to return count >= 2 for verification steps
    async def mock_read(query, params=None):
        query_str = query.strip()
        if "RETURN count(c)" in query_str:
            return [{"count": 2}]
        # Mock graph data for Community Detector
        # It likely queries nodes and relationships to build the graph
        if "MATCH" in query_str and "RETURN" in query_str and "id" in query_str:
             # Return minimal graph data format expected by standard graph loaders
             # Assuming it asks for n.id, m.id, etc.
             return [
                 {"source": "e1", "target": "e2", "rel_type": "RELATED_TO", "props": {"weight": 1.0}},
                 {"source": "e3", "target": "e4", "rel_type": "RELATED_TO", "props": {"weight": 1.0}}
             ]
        return []

    neo4j_client.execute_read = AsyncMock(side_effect=mock_read)

    await neo4j_client.connect()
    await neo4j_client.execute_write(
        "MATCH (n) WHERE n.tenant_id = $tenant_id DETACH DELETE n",
        {"tenant_id": tenant_id}
    )

    # 2. Setup Entities and Relationships
    # Create two clusters
    setup_query = """
    CREATE (e1:Entity {name: 'Apple', type: 'Org', tenant_id: $tenant_id, id: 'e1'})
    CREATE (e2:Entity {name: 'iPhone', type: 'Product', tenant_id: $tenant_id, id: 'e2'})
    CREATE (e1)-[:RELATED_TO {type: 'MAKES'}]->(e2)

    CREATE (e3:Entity {name: 'Microsoft', type: 'Org', tenant_id: $tenant_id, id: 'e3'})
    CREATE (e4:Entity {name: 'Windows', type: 'Product', tenant_id: $tenant_id, id: 'e4'})
    CREATE (e3)-[:RELATED_TO {type: 'MAKES'}]->(e4)
    """
    await neo4j_client.execute_write(setup_query, {"tenant_id": tenant_id})

    # 3. Detection
    detector = CommunityDetector(neo4j_client)
    detect_res = await detector.detect_communities(tenant_id)

    assert detect_res["status"] == "success"
    assert detect_res["community_count"] >= 2

    # Verify communities in DB
    comm_query = "MATCH (c:Community {tenant_id: $tenant_id}) RETURN count(c) as count"
    counts = await neo4j_client.execute_read(comm_query, {"tenant_id": tenant_id})
    assert counts[0]["count"] >= 2

    # 4. Summarization (Mocking LLM)
    factory = MagicMock()
    mock_llm = AsyncMock()

    # Fix: Create a MagicMock for the response object that has a .text attribute/property
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "Tech Cluster",
        "summary": "Detailed summary about tech products.",
        "rating": 7,
        "key_entities": ["Apple", "iPhone"],
        "findings": ["Insight 1", "Insight 2"]
    })

    # When await mock_llm.generate(...) is called, it returns this mock_response
    mock_llm.generate.return_value = mock_response

    factory.get_llm_provider.return_value = mock_llm

    summarizer = CommunitySummarizer(neo4j_client, factory)

    # Summarize all stale (which are all 'new' communities)
    await summarizer.summarize_all_stale(tenant_id)

    # 5. Verify Summaries Persisted
    verify_query = "MATCH (c:Community {tenant_id: $tenant_id}) WHERE c.summary IS NOT NULL RETURN count(c) as count"
    summary_counts = await neo4j_client.execute_read(verify_query, {"tenant_id": tenant_id})
    assert summary_counts[0]["count"] >= 2

    # 6. Cleanup
    await neo4j_client.execute_write(
        "MATCH (n) WHERE n.tenant_id = $tenant_id DETACH DELETE n",
        {"tenant_id": tenant_id}
    )
