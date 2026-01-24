
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import platform
neo4j_client = platform.neo4j_client


async def debug_doc():
    target_id = "doc_1e54a28af3e548d6" # The ID from enrich_document.py
    print(f"Checking Document: {target_id}")
    
    query = """
    MATCH (d:Document {id: $id}) 
    RETURN d, labels(d) as labels 
    """
    results = await neo4j_client.execute_read(query, {"id": target_id})
    
    if not results:
        print(f"Document {target_id} NOT FOUND in Neo4j.")
    else:
        print("Found Document node:")
        for key, value in results[0]['d'].items():
            print(f"  {key}: {value}")
            
        # Check chunk connectivity
        query_chunks = """
            MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk)
            RETURN count(c) as chunk_count
        """
        chunk_res = await neo4j_client.execute_read(query_chunks, {"id": target_id})
        print(f"Connected chunks: {chunk_res[0]['chunk_count']}")

        # Check Similarity Edges via this document
        query_sim = """
            MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk)
            MATCH (c)-[r:SIMILAR_TO]->(c2:Chunk)
            RETURN count(r) as sim_count
        """
        sim_res = await neo4j_client.execute_read(query_sim, {"id": target_id})
        print(f"Similarity edges from stats query: {sim_res[0]['sim_count']}")
        
        # Check Similarity Edges ignoring Document tenant_id (backend uses tenant_id in query!)
        # The backend query is: MATCH (d:Document {id: $document_id, tenant_id: $tenant_id})...
        # If tenant_id property is missing, backend query fails.

    # Also check the 'other' document I found earlier
    print("\nChecking ghost document doc_2e6735d360964b3f:")
    results_2 = await neo4j_client.execute_read(query, {"id": "doc_2e6735d360964b3f"})
    if results_2:
        print("Ghost document exists.")
    else:
        print("Ghost document gone.")

if __name__ == "__main__":
    asyncio.run(debug_doc())
