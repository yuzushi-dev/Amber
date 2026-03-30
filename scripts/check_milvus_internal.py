
import sys

try:
    from pymilvus import Collection, connections, utility
except ImportError:
    print("pymilvus not installed")
    sys.exit(1)

print("Connecting to Milvus...")
try:
    connections.connect(host="milvus", port="19530")
except Exception as e:
    print(f"Failed to connect: {e}")
    sys.exit(1)


expr = "document_id == 'doc_171b0ed9dc29bd6a'"
collections_to_check = ["amber_default", "document_chunks"]
for col_name in collections_to_check:
    if utility.has_collection(col_name):
        print(f"Checking collection {col_name}...")
        collection = Collection(col_name)
        collection.load()
        try:
            res = collection.query(expr, output_fields=["chunk_id"])
            print(f"Found {len(res)} vectors for document doc_171b0ed9dc29bd6a in {col_name}")
        except Exception as e:
            print(f"Error querying {col_name}: {e}")
    else:
        print(f"Collection {col_name} does not exist.")
