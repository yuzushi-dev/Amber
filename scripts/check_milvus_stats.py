
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.api.config import settings
from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore


async def check_milvus():
    print("Checking Milvus stats...")

    milvus_config = MilvusConfig(
        host=settings.db.milvus_host,
        port=settings.db.milvus_port,
        collection_name=f"amber_{settings.tenant_id}"
    )

    store = MilvusVectorStore(milvus_config)
    try:
        await store.connect()
        stats = await store.get_stats()
        print(f"Collection: {stats.get('collection_name')}")
        print(f"Entity Count: {stats.get('num_entities')}")
        if "error" in stats:
            print(f"Error details: {stats['error']}")

    except Exception as e:
        print(f"Error checking Milvus: {e}")
    finally:
        await store.disconnect()

if __name__ == "__main__":
    asyncio.run(check_milvus())
