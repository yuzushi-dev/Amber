
import asyncio
from pymilvus import connections, Collection

async def main():
    connections.connect(host="localhost", port=19530)
    try:
        c = Collection("amber_default")
        c.load()
        res = c.query(expr="", limit=5, output_fields=["tenant_id", "document_id", "chunk_id"])
        print(f"Sample data: {res}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
