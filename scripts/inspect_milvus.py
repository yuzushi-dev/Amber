import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import platform


async def inspect_milvus():
    print("Initializing Platform/Milvus...")
    await platform.initialize()
    store = platform.milvus_vector_store
    await store.connect()

    tenant_id = "default"

    print(f"Checking vectors for tenant: '{tenant_id}'")

    # 1. Count using query/count (if possible) or just num_entities
    stats = await store.get_stats()
    print(f"Collection Stats: {stats}")

    # 2. Try explicit count query
    expr = f'{store.FIELD_TENANT_ID} == "{tenant_id}"'
    try:
        # Pymilvus query with count(*) is supported in newer versions, or just query limit 1
        res = store._collection.query(expr, output_fields=["count(*)"])
        print(f"Count Query Result: {res}")
    except Exception as e:
        print(f"Count Query Failed: {e}")
        # Manual count via simple query ids
        try:
             res = store._collection.query(expr, output_fields=[store.FIELD_CHUNK_ID], limit=16384)
             print(f"Manual Count (limit 16k): {len(res)}")
        except Exception as e2:
             print(f"Manual ID Query Failed: {e2}")

    # 3. Test export_vectors
    print("Testing export_vectors()...")
    count = 0
    try:
        async for vec in store.export_vectors(tenant_id):
            count += 1
            if count % 100 == 0:
                print(f"  Exported {count}...")
    except Exception as e:
        print(f"Export Failed: {e}")

    print(f"Total Exported via Generator: {count}")

    await platform.shutdown()

if __name__ == "__main__":
    asyncio.run(inspect_milvus())
