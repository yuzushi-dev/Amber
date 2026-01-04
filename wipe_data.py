import asyncio
from pymilvus import connections, utility, Collection
from neo4j import GraphDatabase

def wipe_all_data():
    print("=== STARTING DATA WIPE ===")
    
    # 1. Wipe Milvus
    print("\n[Milvus] Connecting...")
    try:
        connections.connect(host='milvus', port='19530')
        collections = utility.list_collections()
        print(f"[Milvus] Found collections: {collections}")
        
        for name in collections:
            print(f"[Milvus] Dropping collection: {name}")
            utility.drop_collection(name)
        
        print("[Milvus] Wipe complete.")
    except Exception as e:
        print(f"[Milvus] Error: {e}")

    # 2. Wipe Neo4j
    print("\n[Neo4j] Connecting...")
    try:
        # Default credentials from docker-compose
        uri = "bolt://neo4j:7687"
        auth = ("neo4j", "graphrag123") # Correct from docker-compose
        
        # Need to read config to be sure, assuming defaults for now or checking env
        # But this runs inside container so we can try default
        
        with GraphDatabase.driver(uri, auth=auth) as driver:
            with driver.session() as session:
                print("[Neo4j] Deleting all nodes and relationships...")
                session.run("MATCH (n) DETACH DELETE n")
                
        print("[Neo4j] Wipe complete.")
    except Exception as e:
        print(f"[Neo4j] Error: {e}")
        print("[Neo4j] Note: If auth failed, check your NEO4J_AUTH env var.")

if __name__ == "__main__":
    wipe_all_data()
