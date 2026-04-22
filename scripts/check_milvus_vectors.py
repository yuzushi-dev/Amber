
from pymilvus import Collection, connections, utility

print("Connecting to Milvus...")
connections.connect(host="localhost", port="19530")

collection_name = "amber_docs_default"  # Assuming default collection name
if not utility.has_collection(collection_name):
    print(f"Collection {collection_name} does not exist.")
    exit(0)

print(f"Collection {collection_name} exists. Load it.")
collection = Collection(collection_name)
collection.load()

# Query for chunks of the document
expr = "document_id == 'doc_171b0ed9dc29bd6a'"
res = collection.query(expr, output_fields=["chunk_id", "document_id"])

print(f"Found {len(res)} vectors for document doc_171b0ed9dc29bd6a")
if len(res) > 0:
    print("Sample vector IDs:", [r['chunk_id'] for r in res[:5]])
