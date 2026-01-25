
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

async def verify_stale_communities():
    print("="*50)
    print("VERIFYING STALE COMMUNITIES")
    print("="*50)

    g_client = Neo4jClient(
        uri=settings.db.neo4j_uri.replace("neo4j:7687", "localhost:7687"),
        user=settings.db.neo4j_user,
        password=settings.db.neo4j_password
    )
    await g_client.connect()

    # 1. Communities with no members (leaf entities)
    # GraphRAG structure: Community -> HAS_MEMBER -> Entity (or sub-community?)
    # Usually: Community -> HAS_MEMBER -> Entity.
    # Hierarchical: Community -> PARENT_OF -> Community.
    
    # Check if communities strictly have NO members.
    query_empty_comms = """
    MATCH (c:Community)
    WHERE NOT (c)-[:HAS_MEMBER]->(:Entity)
    RETURN count(c) as empty_count
    """
    res = await g_client.execute_read(query_empty_comms)
    print(f"Communities with no Entity members: {res[0]['empty_count']}")
    
    # 2. Total Communities
    res_total = await g_client.execute_read("MATCH (c:Community) RETURN count(c) as total")
    print(f"Total Communities: {res_total[0]['total']}")
    
    await g_client.close()

if __name__ == "__main__":
    asyncio.run(verify_stale_communities())
