import asyncio
from pymilvus import connections, utility, Collection

def fix_milvus():
    print("Connecting to Milvus...")
    connections.connect(host='milvus', port='19530')
    
    collection_name = 'document_chunks'
    if not utility.has_collection(collection_name):
        print(f"Collection {collection_name} does not exist!")
        return

    c = Collection(collection_name)
    print(f"Collection loaded: {collection_name}")
    print(f"Entities: {c.num_entities}")

    print("Releasing collection...")
    c.release()

    # Drop existing index
    try:
        if c.has_index():
            print("Dropping existing index...")
            c.drop_index()
    except Exception as e:
        print(f"Error dropping index: {e}")

    print("Flushing collection...")
    c.flush() # Ensure all data is visible

    print("Creating new index (FLAT)...")
    index_params = {
        "metric_type": "COSINE",
        "index_type": "FLAT",
        "params": {}
    }
    c.create_index(field_name="vector", index_params=index_params)
    print("Index created.")

    print("Loading collection...")
    c.load()
    print("Collection loaded successfully!")
    
    print("Entities after load:", c.num_entities)

if __name__ == "__main__":
    fix_milvus()
