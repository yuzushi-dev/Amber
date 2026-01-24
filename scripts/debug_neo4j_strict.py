
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import platform
neo4j_client = platform.neo4j_client


async def debug_doc():
    target_id = "doc_1e54a28af3e548d6"
    tenant_id = "default"
    
    # Exact backend query from documents.py
    sim_cypher = """
        MATCH (d:Document {id: $document_id, tenant_id: $tenant_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[r:SIMILAR_TO]->(c2:Chunk)
        RETURN count(DISTINCT r) as sim_count
    """
    
    print(f"Executing Query for {target_id} tenant={tenant_id}...")
    sim_records = await neo4j_client.execute_read(
        sim_cypher,
        {"document_id": target_id, "tenant_id": tenant_id}
    )
    
    if sim_records:
        print(f"Count: {sim_records[0]['sim_count']}")
    else:
        print("No records returned.")

if __name__ == "__main__":
    asyncio.run(debug_doc())
