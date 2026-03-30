import asyncio

from pymilvus import connections, utility

from src.api.config import settings
from src.workers.tasks import _process_communities_async


async def run():
    print("Connecting to Milvus...")
    connections.connect(host=settings.db.milvus_host, port=settings.db.milvus_port)
    if utility.has_collection("community_embeddings"):
        utility.drop_collection("community_embeddings")
        print("Dropped community_embeddings collection.")
    connections.disconnect("default")

    print("Re-running community detection and embeddings...")
    res = await _process_communities_async("default")
    print(res)

if __name__ == "__main__":
    asyncio.run(run())
