
import asyncio
import logging
import sys
import os
from pprint import pprint

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import platform, configure_settings
from src.api.config import settings
from src.core.database.session import configure_database, get_session_maker
from sqlalchemy import text

async def main():
    print("DEBUG: Configuring settings...")
    configure_settings(settings)
    print(f"DEBUG: Used DATABASE_URL: {settings.db.database_url}")
    configure_database(settings.db.database_url)
    
    print("DEBUG: Initializing platform...")
    await platform.initialize()
    
    try:
        # Check Postgres
        print("\n--- CHECKING POSTGRES ---")
        async_session_maker = get_session_maker()
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT count(*) FROM documents"))
            count = result.scalar()
            print(f"Postgres Document Count: {count}")
            
            result = await session.execute(text("SELECT count(*) FROM chunks"))
            chunk_count = result.scalar()
            print(f"Postgres Chunk Count: {chunk_count}")

        # Check Milvus
        print("\n--- CHECKING MILVUS ---")
        try:
            from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore, MilvusConfig
             # We can't easily access the client from here without building the service or duplicating logic
             # But platform doesn't manage milvus client directly for public use, it's inside VectorStore
            
            milvus_config = MilvusConfig(
                host=settings.db.milvus_host,
                port=settings.db.milvus_port,
                dimensions=settings.embedding_dimensions or 768,
            )
            store = MilvusVectorStore(milvus_config)
            await store.connect()
            print("Milvus Connected.")
            
            store = MilvusVectorStore(milvus_config)
            await store.connect()
            print("Milvus Connected.")
            
            stats = await store.get_stats()
            print(f"Milvus Stats: {stats}")
            
            await store.disconnect()

        except Exception as e:
            print(f"Milvus Check Failed: {e}")

        # Check Neo4j
        print("\n--- CHECKING NEO4J ---")
        try:
            client = platform.neo4j_client
            # Verify connectivity
            await client.verify_connectivity() 
            print("Neo4j Connected.")
            # Maybe count nodes?
            # client.execute_query is the method
            # res = await client.execute_query("MATCH (n) RETURN count(n) as count")
            # print(f"Neo4j Node Count: {res[0]['count']}")
        except Exception as e:
             print(f"Neo4j Check Failed: {e}")

    except Exception as e:
        logger.exception(f"DEBUG: Error during execution: {e}")
    finally:
        print("\nDEBUG: Shutting down platform...")
        await platform.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
