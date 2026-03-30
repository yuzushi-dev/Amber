
import asyncio
import sys

# Ensure custom packages are loadable
if "/app/.packages" not in sys.path:
    sys.path.insert(0, "/app/.packages")

from src.amber_platform.composition_root import configure_settings, platform
from src.api.config import settings


async def check_recent_summaries():
    configure_settings(settings)
    # await platform.db.connect()
    await platform.neo4j_client.connect()

    # Calculate timestamp for 1 hour ago
    # Neo4j datetime() is ISO 8601 string or specific Neo4j type.
    # Let's just count summaries that are NOT NULL first.

    query = """
    MATCH (c:Community)
    WHERE c.summary IS NOT NULL
    RETURN count(c) as total
    """
    result = await platform.neo4j_client.execute_read(query)
    total = result[0]["total"]

    print(f"Total communities with summary: {total}")

    # Check for recent updates if possible (assuming last_updated_at is stored)
    # The summarizer sets: c.last_updated_at = datetime()

    query_recent = """
    MATCH (c:Community)
    WHERE c.summary IS NOT NULL 
      AND c.last_updated_at > datetime() - duration('PT1H')
    RETURN count(c) as recent
    """
    result_recent = await platform.neo4j_client.execute_read(query_recent)
    recent = result_recent[0]["recent"]

    print(f"Communities summarized in the last hour: {recent}")

    await platform.neo4j_client.close()

if __name__ == "__main__":
    asyncio.run(check_recent_summaries())
