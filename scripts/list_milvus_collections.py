
import asyncio
from pymilvus import connections, utility

async def main():
    connections.connect(host="localhost", port=19530)
    print("Connected to Milvus.")
    
    collections = utility.list_collections()
    print(f"Collections found: {collections}")
    
    for name in collections:
        print(f"\nCollection: {name}")
        try:
             from pymilvus import Collection
             c = Collection(name)
             c.load()
             print(f" - Count: {c.num_entities}")
             print(f" - Schema: {c.schema}")
        except Exception as e:
            print(f" - Error details: {e}")

if __name__ == "__main__":
    asyncio.run(main())
