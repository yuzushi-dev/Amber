
import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

sys.path.append(os.getcwd())
load_dotenv()

from src.api.config import settings
from src.core.graph.infrastructure.neo4j_client import Neo4jClient

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def investigate_relationships():
    print("="*50)
    print("INVESTIGATING 429 RELATIONSHIPS")
    print("="*50)

    g_client = Neo4jClient(
        uri=settings.db.neo4j_uri.replace("neo4j:7687", "localhost:7687"),
        user=settings.db.neo4j_user,
        password=settings.db.neo4j_password
    )
    await g_client.connect()

    # 1. Get total relationship count
    res = await g_client.execute_read("MATCH ()-[r]->() RETURN count(r) as count")
    print(f"Total Relationships: {res[0]['count']}")

    # 2. Inspect what these relationships connect
    # Are they Entity-Entity? Chunk-Entity?
    query_types = """
    MATCH (a)-[r]->(b)
    RETURN labels(a) as source_label, type(r) as rel_type, labels(b) as target_label, count(r) as freq
    ORDER BY freq DESC
    """
    res_types = await g_client.execute_read(query_types)
    print("\nRelationship Distribution:")
    for row in res_types:
        print(f" - {row['source_label']} -[{row['rel_type']}]-> {row['target_label']}: {row['freq']}")

    # 3. Check for Orphan Islands (Entities connected ONLY to other Entities, not reachable from valid Chunks)
    # This is expensive to check perfectly, but we can check if they are part of a 'valid' path.
    # Simpler check: Are there relationships where source/target are NOT connected to any Chunk?
    
    # Let's check a sample of these relationships
    query_sample = """
    MATCH (a)-[r]->(b)
    WHERE NOT (a:Chunk) AND NOT (b:Chunk)
    RETURN a.name, type(r), b.name, r.tenant_id
    LIMIT 10
    """
    res_sample = await g_client.execute_read(query_sample)
    print("\nSample Entity-Entity Relationships:")
    for row in res_sample:
        print(f" - {row['a.name']} -[{row['type(r)']}]-> {row['b.name']} ({row['r.tenant_id']})")

    await g_client.close()

if __name__ == "__main__":
    asyncio.run(investigate_relationships())
