
import asyncio
import sys
import os

sys.path.append(os.getcwd())

from src.amber_platform.composition_root import platform
neo4j_client = platform.neo4j_client

from src.api.config import settings

async def check_edges(filename_pattern: str):
    print("Checking for SIMILAR_TO edges...")
    
    cypher = """
        MATCH (d:Document)
        WHERE d.filename CONTAINS $filename
        MATCH (d)-[:HAS_CHUNK]->(c:Chunk)-[r:SIMILAR_TO]->(c2:Chunk)
        RETURN count(r) as edge_count
    """
    
    try:
        results = await neo4j_client.execute_read(cypher, {"filename": filename_pattern})
        count = results[0]["edge_count"] if results else 0
        print(f"Found {count} SIMILAR_TO edges for documents matching '{filename_pattern}'.")
    except Exception as e:
        print(f"Error querying Neo4j: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/check_edges.py <filename_pattern>")
        sys.exit(1)
    
    asyncio.run(check_edges(sys.argv[1]))
