
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import platform
neo4j_client = platform.neo4j_client


async def count_edges():
    query = "MATCH ()-[r:SIMILAR_TO]->() RETURN count(r) as count"
    results = await neo4j_client.execute_read(query)
    count = results[0]["count"]
    print(f"Total SIMILAR_TO edges: {count}")

if __name__ == "__main__":
    asyncio.run(count_edges())
