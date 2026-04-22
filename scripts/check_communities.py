import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import platform


async def main():
    try:
        await platform.neo4j_client.connect()
        # Query community counts by status
        query = "MATCH (c:Community) RETURN c.status as status, count(c) as count"
        results = await platform.neo4j_client.execute_read(query, {})
        print("Community Status Counts:")
        for res in results:
            print(f"- {res['status']}: {res['count']}")

        # Query total communities
        total_query = "MATCH (c:Community) RETURN count(c) as total"
        total_res = await platform.neo4j_client.execute_read(total_query, {})
        print(f"Total Communities: {total_res[0]['total']}")

        # Communities needing summarization
        stale_query = "MATCH (c:Community) WHERE c.summary IS NULL OR c.is_stale = true RETURN count(c) as stale"
        stale_res = await platform.neo4j_client.execute_read(stale_query, {})
        print(f"Communities Needing Summarization (stale or no summary): {stale_res[0]['stale']}")

    finally:
        await platform.neo4j_client.close()

if __name__ == "__main__":
    asyncio.run(main())
