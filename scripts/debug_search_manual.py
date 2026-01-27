
import sys
import os
import asyncio
from pymilvus import connections, Collection

# Add src to path
sys.path.append("/home/daniele/Amber_2.0")

# Simulate config
PROMPT = "determinism"
TENANT_ID = "default"
COLLECTION_NAME = "amber_default"

async def main():
    print("Connecting to Milvus...")
    connections.connect(host="localhost", port=19530)
    
    col = Collection(COLLECTION_NAME)
    col.load()
    print(f"Collection {COLLECTION_NAME} loaded. Count: {col.num_entities}")
    
    # 1. Fetch one document to see content
    res = col.query(expr="", limit=1, output_fields=["chunk_id", "content", "metadata", "tenant_id"])
    print(f"Sample Document: {res[0]}")
    
    # 2. Embed query using Ollama directly (mimic EmbeddingService)
    # We use requests just like the service
    import requests
    
    print(f"Embedding query: '{PROMPT}'...")
    response = requests.post(
        "http://localhost:11434/api/embeddings",
        json={
            "model": "nomic-embed-text",
            "prompt": PROMPT
        }
    )
    
    if response.status_code != 200:
        print(f"Error embedding: {response.text}")
        return
        
    embedding = response.json()["embedding"]
    print(f"Embedding generated. Dim: {len(embedding)}")
    
    # 3. Search Milvus
    search_params = {
        "metric_type": "COSINE",
        "params": {"ef": 128} # HNSW param
    }
    
    print(f"Searching {COLLECTION_NAME} with tenant_id={TENANT_ID}...")
    
    # Filter
    expr = f'tenant_id == "{TENANT_ID}"'
    
    results = col.search(
        data=[embedding],
        anns_field="vector",
        param=search_params,
        limit=5,
        expr=expr,
        output_fields=["chunk_id", "score", "content"]
    )
    
    print(f"Search Results: {len(results[0])}")
    for hit in results[0]:
        print(f"Hit: {hit.id}, Score: {hit.score}")

if __name__ == "__main__":
    asyncio.run(main())
