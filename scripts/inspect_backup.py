import asyncio
import io
import os
import sys
import zipfile

# Add src to path
sys.path.append(os.getcwd())

from src.amber_platform.composition_root import get_settings_lazy, platform


async def inspect_latest_backup():
    print("Connecting to MinIO...")
    settings = get_settings_lazy()

    # MinIOClient wrapper instance
    minio_wrapper = platform.minio_client

    bucket_name = minio_wrapper.bucket_name
    print(f"Bucket: {bucket_name}")

    # List objects in backup_archives/ using raw client
    # Debug: List everything
    print(f"Listing all objects in {bucket_name}...")
    objects = minio_wrapper.client.list_objects(bucket_name, recursive=True)

    # Materialize iterator to list to reuse and debug
    all_objs = list(objects)
    print(f"Found {len(all_objs)} objects.")
    for o in all_objs[:5]:
        print(f" - {o.object_name}")

    # Filter for zips in backups/
    backups = [obj for obj in all_objs if obj.object_name.startswith("backups/") and obj.object_name.endswith(".zip")]


    if not backups:
        print("No backups found in storage.")
        return

    # Sort by last_modified (Miniobject usually has this)
    backups.sort(key=lambda x: x.last_modified, reverse=True)

    latest_backup = backups[0]
    print(f"Latest Backup: {latest_backup.object_name}")
    print(f"Size: {latest_backup.size / 1024 / 1024:.2f} MB")
    print("-" * 40)

    # Download
    print("Downloading for inspection...")
    data = minio_wrapper.get_file(latest_backup.object_name)
    # data is bytes

    # Open Zip
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        print("\n[Archive Contents]")
        # Print tabular
        print(f"{'Filename':<40} | {'Size (KB)':<10}")
        print("-" * 55)

        has_dump = False
        has_vectors = False
        has_graph = False

        for info in zf.infolist():
            size_kb = info.file_size / 1024
            print(f"{info.filename:<40} | {size_kb:.2f}")

            if info.filename == "ingestion/chunks.json":
                import json
                try:
                    chunks_data = json.loads(zf.read("ingestion/chunks.json"))
                    print(f"  [Chunks Analysis]: Found {len(chunks_data)} chunks.")
                    if chunks_data:
                        sample = chunks_data[0]
                        print(f"  Sample Chunk ID: {sample.get('id')}")
                        print(f"  Embedding Status: {sample.get('embedding_status')}")
                except Exception as e:
                    print(f"  Error reading chunks.json: {e}")

            if info.filename == "database/postgres_dump.sql":
                has_dump = True
                if info.file_size < 100: # suspiciously small
                    print("  WARNING: Dump file is extremely small!")

            if info.filename == "vectors/vectors.jsonl":
                has_vectors = True

            if info.filename == "graph/graph.jsonl":
                has_graph = True

        print("-" * 55)
        if has_dump:
            print("✅ Postgres Dump found")
        else:
            print("❌ Postgres Dump MISSING")

        if has_vectors:
            print("✅ Vectors found")
        else:
            print("⚠️ Vectors MISSING (Normal if no vectors exist)")

        if has_graph:
            print("✅ Graph data found")
        else:
            print("⚠️ Graph data MISSING (Normal if no graph data exists)")

if __name__ == "__main__":
    asyncio.run(inspect_latest_backup())
