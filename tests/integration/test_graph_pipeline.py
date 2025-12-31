import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from src.core.graph.neo4j_client import neo4j_client
from src.core.graph.writer import graph_writer
from src.core.graph.schema import NodeLabel, RelationshipType
from src.core.prompts.entity_extraction import ExtractionResult, ExtractedEntity, ExtractedRelationship

@pytest.mark.asyncio
async def test_graph_writer_integration():
    """
    Test writing to the real Neo4j instance and verifying data.
    """
    # 1. Setup Data
    tenant_id = "test_tenant_integration"
    doc_id = "doc_integration_1"
    chunk_id = "chunk_integration_1"
    
    # Cleanup before test
    await neo4j_client.connect()
    try:
        await neo4j_client.execute_write(
            f"MATCH (n) WHERE n.tenant_id = $tenant_id DETACH DELETE n", 
            {"tenant_id": tenant_id}
        )
    except Exception as e:
        pytest.fail(f"Failed to cleanup Neo4j: {e}")

    # 2. Prepare Extraction Result
    extraction_result = ExtractionResult(
        entities=[
            ExtractedEntity(name="Neo4j", type="TECHNOLOGY", description="Graph Database"),
            ExtractedEntity(name="Python", type="TECHNOLOGY", description="Programming Language")
        ],
        relationships=[
            ExtractedRelationship(
                source="Python", 
                target="Neo4j", 
                type="CONNECTS_TO", 
                description="Python driver connects to Neo4j",
                weight=9
            )
        ]
    )

    # 3. Write to Graph
    try:
        await graph_writer.write_extraction_result(doc_id, chunk_id, tenant_id, extraction_result)
    except Exception as e:
        pytest.fail(f"GraphWriter failed: {e}")

    # 4. Verify in Neo4j
    # Check Entities
    query_entities = f"""
    MATCH (e:{NodeLabel.Entity.value}) 
    WHERE e.tenant_id = $tenant_id 
    RETURN e.name as name, e.type as type
    ORDER BY e.name
    """
    records = await neo4j_client.execute_read(query_entities, {"tenant_id": tenant_id})
    
    assert len(records) == 2
    names = sorted([r["name"] for r in records])
    assert names == ["Neo4j", "Python"]
    
    # Check Relationship
    query_rels = f"""
    MATCH (s:{NodeLabel.Entity.value})-[r:{RelationshipType.RELATED_TO.value}]->(t:{NodeLabel.Entity.value})
    WHERE s.tenant_id = $tenant_id 
    RETURN s.name as source, t.name as target, r.type as type, r.weight as weight
    """
    records_rels = await neo4j_client.execute_read(query_rels, {"tenant_id": tenant_id})
    
    assert len(records_rels) == 1
    rel = records_rels[0]
    assert rel["source"] == "Python"
    assert rel["target"] == "Neo4j"
    assert rel["type"] == "CONNECTS_TO"
    assert rel["weight"] == 9

    # Check Provenance (Chunk -> Entity)
    query_prov = f"""
    MATCH (c:{NodeLabel.Chunk.value})-[r:{RelationshipType.MENTIONS.value}]->(e:{NodeLabel.Entity.value})
    WHERE c.id = $chunk_id
    RETURN count(e) as count
    """
    records_prov = await neo4j_client.execute_read(query_prov, {"chunk_id": chunk_id})
    assert records_prov[0]["count"] == 2

    # Cleanup
    await neo4j_client.execute_write(
        f"MATCH (n) WHERE n.tenant_id = $tenant_id DETACH DELETE n", 
        {"tenant_id": tenant_id}
    )
