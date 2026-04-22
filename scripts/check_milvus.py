import asyncio
import logging

# Configure logging
from src.api.config import settings

logging.basicConfig(level=logging.INFO)
from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore


async def check_milvus():
    print(f"Checking Milvus at {settings.db.milvus_host}:{settings.db.milvus_port}")

    config = MilvusConfig(
        host=settings.db.milvus_host,
        port=settings.db.milvus_port,
        collection_name="document_chunks", # Default name from milvus.py
        dimensions=1536
    )

    store = MilvusVectorStore(config)

    try:
        await store.connect()

        # Get stats
        stats = await store.get_stats()
        print("\n--- Collection Stats ---")
        for k, v in stats.items():
            print(f"{k}: {v}")

        num_entities = stats.get("num_entities", 0)

        if num_entities > 0:
            print("\nAttempting dummy search...")
            # Create a zero vector of correct dimension
            dummy_vector = [0.001] * config.dimensions

            results = await store.search(
                query_vector=dummy_vector,
                tenant_id=settings.tenant_id,
                limit=3
            )

            print(f"\nFound {len(results)} results:")
            for i, r in enumerate(results):
                content = r.metadata.get('content', '')
                preview = content[:100].replace('\n', ' ')
                print(f" {i+1}. [Score: {r.score:.4f}] {preview}...")
        else:
            print("\nCollection is empty.")

    except Exception as e:
        print(f"\nError: {e}")
    finally:
        await store.disconnect()

if __name__ == "__main__":
    asyncio.run(check_milvus())
