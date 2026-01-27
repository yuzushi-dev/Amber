
import asyncio
from pymilvus import connections, Collection

async def main():
    connections.connect(host="localhost", port=19530)
    try:
        c = Collection("amber_default")
        c.load()
        print(f"amber_default count: {c.num_entities}")
        print(f"amber_default schema: {c.schema}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
