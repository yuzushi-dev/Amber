"""
Graph Inspection Script
=======================

Queries Neo4j for counts of all nodes and relationships to identify what remains.
"""

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

from src.api.config import settings
from src.core.graph.infrastructure.neo4j_client import Neo4jClient

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

async def inspect():
    print("\n" + "="*50)
    print("   NEO4J GRAPH INSPECTION")
    print("="*50 + "\n")

    # Connect to Neo4j
    # Adjust URI for local execution if needed, similar to cleanup script
    uri = settings.db.neo4j_uri
    if "neo4j:7687" in uri:
         uri = uri.replace("neo4j:7687", "localhost:7687")

    print(f"Connecting to: {uri}")

    client = Neo4jClient(
        uri=uri,
        user=settings.db.neo4j_user,
        password=settings.db.neo4j_password
    )

    try:
        await client.connect()

        # 1. Count All Nodes by Label
        print("\n--- Node Counts by Label ---")
        node_counts = await client.execute_read(
            "MATCH (n) RETURN labels(n) as labels, count(n) as count ORDER BY count DESC"
        )
        if not node_counts:
            print("No nodes found.")
        else:
            for record in node_counts:
                print(f"{record['labels']}: {record['count']}")

        # 2. Count All Relationships by Type
        print("\n--- Relationship Counts by Type ---")
        rel_counts = await client.execute_read(
            "MATCH ()-[r]->() RETURN type(r) as type, count(r) as count ORDER BY count DESC"
        )
        if not rel_counts:
            print("No relationships found.")
        else:
            for record in rel_counts:
                print(f"{record['type']}: {record['count']}")

        # 3. Sample Entities if any
        print("\n--- Sample Entities (Limit 5) ---")
        entities = await client.execute_read(
             "MATCH (e:Entity) RETURN e.name as name, e.id as id LIMIT 5"
        )
        if not entities:
            print("No entities found.")
        else:
            for e in entities:
                print(f" - {e['name']} ({e.get('id', 'no-id')})")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.close()
        print("\nInspection complete.")

if __name__ == '__main__':
    asyncio.run(inspect())
