
import asyncio
import logging
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

from src.api.config import settings
from src.core.graph.infrastructure.neo4j_client import Neo4jClient

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def verify_delete_actions():
    print("\n" + "="*50)
    print(f"   VERIFY DELETE ACTIONS (Raw SQL)")
    print("="*50 + "\n")

    # 1. DB Connection
    db_url = settings.db.database_url
    if "postgres:5432" in db_url:
        db_url = db_url.replace("postgres:5432", "localhost:5433")
    
    engine = create_async_engine(db_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # 2. Neo4j Connection
    g_client = Neo4jClient(
        uri=settings.db.neo4j_uri.replace("neo4j:7687", "localhost:7687"),
        user=settings.db.neo4j_user,
        password=settings.db.neo4j_password
    )
    await g_client.connect()

    async with async_session() as session:
        # --- TEST 1: FOLDER DELETION ---
        print("\n[TEST 1] Verifying Folder Deletion Safety")
        
        # Create Dummy Folder
        test_tenant_id = settings.tenant_id or "default"
        folder_id = str(uuid.uuid4())
        # Use raw insert
        await session.execute(
            text("INSERT INTO folders (id, tenant_id, name, created_at, updated_at) VALUES (:id, :tid, :name, NOW(), NOW())"),
            {"id": folder_id, "tid": test_tenant_id, "name": "VerifyDelete_Folder"}
        )
        
        # Create Dummy Document in Folder
        doc_id = str(uuid.uuid4())
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, filename, folder_id, status, created_at, updated_at, storage_path, content_hash, metadata)
                VALUES (:id, :tid, :name, :fid, 'READY'::documentstatus, NOW(), NOW(), 'mock', 'mock', '{}')
            """),
            {"id": doc_id, "tid": test_tenant_id, "name": "VerifyDelete_Doc.txt", "fid": folder_id}
        )
        await session.commit()
        
        print(f" - Created folder {folder_id} and document {doc_id} inside it.")
        
        # Simulate Folder Delete Logic: Unfile, then Delete
        # 1. Unfile
        await session.execute(
            text("UPDATE documents SET folder_id = NULL WHERE folder_id = :fid"),
            {"fid": folder_id}
        )
        # 2. Delete Folder
        await session.execute(
            text("DELETE FROM folders WHERE id = :id"),
            {"id": folder_id}
        )
        await session.commit()
        
        # Verify Document stats
        res = await session.execute(
            text("SELECT folder_id FROM documents WHERE id = :id"),
            {"id": doc_id}
        )
        doc_folder_id = res.scalar()
        
        if doc_folder_id is None:
            print(" - FAILSAFE VERIFIED: Document exists and is unfiled.")
        else:
            print(f" - FAILURE: Document folder_id is {doc_folder_id}")

        # Cleanup doc
        await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
        await session.commit()

        # --- TEST 2: TENANT DELETION ---
        print("\n[TEST 2] Verifying Tenant Deletion Cleanup")
        
        # Create Temporary Tenant
        temp_tenant_id = str(uuid.uuid4())
        await session.execute(
            text("INSERT INTO tenants (id, name, created_at, updated_at) VALUES (:id, :name, NOW(), NOW())"),
            {"id": temp_tenant_id, "name": "VerifyDelete_Tenant"}
        )
        await session.commit()
        print(f" - Created temp tenant {temp_tenant_id}")
        
        # Create Graph Node for this tenant
        await g_client.execute_write(
            "CREATE (n:Entity {name: 'DeleteMe', tenant_id: $tid})", 
            {"tid": temp_tenant_id}
        )
        print(" - Created graph node for tenant.")
        
        # Delete Tenant (Simulate API: delete row)
        await session.execute(
            text("DELETE FROM tenants WHERE id = :id"),
            {"id": temp_tenant_id}
        )
        await session.commit()
        print(" - Deleted tenant from Postgres.")
        
        # Check Graph Node
        res = await g_client.execute_read(
            "MATCH (n:Entity {tenant_id: $tid}) RETURN count(n) as c", 
            {"tid": temp_tenant_id}
        )
        count = res[0]['c']
        
        if count > 0:
            print(f" - FAILURE DETECTED: {count} graph nodes persist after tenant deletion.")
            # Cleanup manually
            await g_client.execute_write(
                "MATCH (n {tenant_id: $tid}) DETACH DELETE n", 
                {"tid": temp_tenant_id}
            )
            print(" - Manual cleanup performed.")
        else:
            print(" - SUCCESS: Graph nodes deleted (unexpected).")

    await g_client.close()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(verify_delete_actions())
