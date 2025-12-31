import asyncio
import logging
from src.core.graph.neo4j_client import neo4j_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_constraints():
    """Verify Neo4j constraints and indexes exist."""
    print("Verifying Neo4j Constraints:")
    
    try:
        await neo4j_client.connect()
        
        # Determine query based on Neo4j version (4.x SHOW CONSTRAINTS vs older call db.constraints)
        # We assume 4.4+ or 5.x
        try:
             constraints = await neo4j_client.execute_read("SHOW CONSTRAINTS")
        except Exception:
             # Fallback for older versions if needed, but we target modern Neo4j
             constraints = []

        found_constraints = [c['name'] for c in constraints]
        print(f"Constraints found: {found_constraints}")
        
        # Check for our specific constraints by name if auto-generated names match, 
        # or just check if we have constraints on the labels.
        # The CREATE CONSTRAINT used names: document_id_unique, chunk_id_unique, community_id_unique
        
        required = ["document_id_unique", "chunk_id_unique", "community_id_unique"]
        missing = [req for req in required if req not in found_constraints]
        
        if missing:
            print(f"❌ Missing constraints: {missing}")
        else:
            print("✅ All required constraints found.")

        # Check Indexes
        # Indexes created: entity_lookup, document_tenant, chunk_document
        indexes = await neo4j_client.execute_read("SHOW INDEXES")
        found_indexes = [i['name'] for i in indexes]
        print(f"Indexes found: {found_indexes}")
        
        required_indexes = ["entity_lookup", "document_tenant", "chunk_document"]
        missing_indexes = [req for req in required_indexes if req not in found_indexes]

        if missing_indexes:
             print(f"❌ Missing indexes: {missing_indexes}")
        else:
             print("✅ All required indexes found.")

    except Exception as e:
        logger.error(f"Verification failed: {e}")
    finally:
        await neo4j_client.close()

if __name__ == "__main__":
    asyncio.run(verify_constraints())
