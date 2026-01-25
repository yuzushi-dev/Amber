
import asyncio
import logging
import uuid
import sys
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

# Ensure we can import from src
import os
sys.path.append(os.getcwd())

load_dotenv()

from src.api.config import settings
from src.core.graph.infrastructure.neo4j_client import Neo4jClient

# Import ALL models to ensure SQLAlchemy registry is complete
from src.core.tenants.domain.tenant import Tenant
from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.folder import Folder

from src.core.tenants.application.tenant_service import TenantService

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def verify_service_deletion():
    print("\n" + "="*50)
    print(f"   VERIFY TENANT SERVICE DELETION")
    print("="*50 + "\n")

    # 1. DB Connection
    db_url = settings.db.database_url
    if "postgres:5432" in db_url:
        db_url = db_url.replace("postgres:5432", "localhost:5433") # Local dev mapping
    
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
        service = TenantService(session)

        # --- TEST: TENANT DELETION ORCHESTRATION ---
        print("\n[TEST] Verifying TenantService Deletion Cleanup")
        
        # A. Create Temporary Tenant via Service
        try:
            temp_tenant_id = str(uuid.uuid4())
            # We create manually to control ID or use service but service generates ID?
            # Service create_tenant generates ID usually? Let's check service signature.
            # create_tenant(name, ...) -> returns Tenant.
            
            # Let's use service to create if possible, but ID is needed for Neo4j consistency?
            # actually service create doesn't allow passing ID.
            # So we create, get ID, then populate Neo4j.
            
            tenant = await service.create_tenant(name=f"VerifyService_{temp_tenant_id[:8]}")
            tenant_id = tenant.id
            print(f" - Created tenant {tenant_id} via Service.")
            
            # B. Create Graph Node for this tenant
            await g_client.execute_write(
                "CREATE (n:Entity {name: 'DeleteMe', tenant_id: $tid})", 
                {"tid": tenant_id}
            )
            print(" - Created graph node for tenant.")
            
            # C. Create Milvus Collection (Mock)
            # We can't easily mock Milvus here without importing massive deps or connecting to real Milvus.
            # But the service code merely tries to delete it. If it fails it logs error. 
            # We primarily care about Neo4j logic being called.
            
            # D. Call Service Delete
            print(" - Calls delete_tenant...")
            result = await service.delete_tenant(tenant_id)
            print(f" - Delete result: {result}")
            
            # E. Verify Neo4j Cleanup
            res = await g_client.execute_read(
                "MATCH (n:Entity {tenant_id: $tid}) RETURN count(n) as c", 
                {"tid": tenant_id}
            )
            count = res[0]['c']
            
            if count == 0:
                print(" - SUCCESS: Graph nodes deleted!")
            else:
                print(f" - FAILURE: {count} graph nodes persist.")
                 # Cleanup manually
                await g_client.execute_write(
                    "MATCH (n {tenant_id: $tid}) DETACH DELETE n", 
                    {"tid": tenant_id}
                )

        except Exception as e:
            print(f" - ERROR: {e}")
            import traceback
            traceback.print_exc()

        # --- TEST: MAINTENANCE PRUNE ORPHANS ---
        print("\n[TEST] Verifying Maintenance Prune Orphans")
        try:
             # 1. Create Orphan Entity (No connections, not in Postgres)
            orphan_id = str(uuid.uuid4())
            await g_client.execute_write(
                "CREATE (n:Entity {name: $id, tenant_id: 'default'})", 
                {"id": orphan_id}
            )
            print(f" - Created orphan node {orphan_id}")
            
            # 2. Call Prune Orphans (simulating API logic)
            # Pass empty valid lists implies everything is orphan? 
            # NO! If we pass empty lists, then "NOT IN []" is TRUE for everything!
            # So passing empty lists would delete EVERYTHING!
            # We must pass "some" IDs or ensure the logic is correct.
            # "WHERE NOT d.id IN $valid_ids" -> If valid_ids is empty, NOT IN [] is True.
            # So we must NOT pass empty lists if we want to save things.
            # But here we want to delete the orphan. The orphan is NOT in the list.
            # So passing ["other"] should trigger deletion of orphan.
            
            dummy_valid_ids = ["keep_me_safe"]
            counts = await g_client.prune_orphans(dummy_valid_ids, dummy_valid_ids)
            print(f" - Prune result: {counts}")
            
            # 3. Verify Orphan is Gone
            res = await g_client.execute_read(
                "MATCH (n:Entity {name: $id}) RETURN count(n) as c", 
                {"id": orphan_id}
            )
            count = res[0]['c']
            if count == 0:
                print(" - SUCCESS: Orphan node deleted!")
            else:
                print(f" - FAILURE: Orphan node persists ({count}).")

            # 4. Test Stale Community Pruning
            print("\n[TEST] Verifying Stale Community Pruning")
            
            # Create a community chain: C1 -> C2 (empty)
            opts = {"c1": "Comm1_" + str(uuid.uuid4()), "c2": "Comm2_" + str(uuid.uuid4())}
            await g_client.execute_write("""
                CREATE (c1:Community {name: $c1})
                CREATE (c2:Community {name: $c2})
                CREATE (c1)-[:PARENT_OF]->(c2)
            """, opts)
            print(f" - Created stale community chain: {opts['c1']} -> {opts['c2']}")
            
            # Prune
            counts = await g_client.prune_orphans(dummy_valid_ids, dummy_valid_ids)
            print(f" - Prune result: {counts}")
            
            # Verify deletion
            res_comm = await g_client.execute_read(
                "MATCH (c:Community) WHERE c.name IN [$c1, $c2] RETURN count(c) as count",
                opts
            )
            val = res_comm[0]['count']
            if val == 0:
                print(" - SUCCESS: Stale communities deleted!")
            else:
                 print(f" - FAILURE: {val} communities persist.")

        except Exception as e:
            print(f" - ERROR in Prune Test: {e}")
            import traceback
            traceback.print_exc()

    await g_client.close()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(verify_service_deletion())
