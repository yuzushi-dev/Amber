import asyncio
import logging

from src.core.graph.neo4j_client import neo4j_client
from src.core.security.graph_acl import graph_acl

logging.basicConfig(level=logging.ERROR)

async def verify_isolation():
    print("Verifying Graph Access Control & Isolation...")
    try:
        await neo4j_client.connect()

        # 1. Setup Data
        # Clear specific test data if exists
        clear_query = """
        MATCH (n) WHERE n.id IN ['docA', 'docB', 'chunkA', 'chunkB'] OR n.name IN ['EntityA', 'EntityB']
        DETACH DELETE n
        """
        await neo4j_client.execute_write(clear_query)

        setup_query = """
        MERGE (da:Document {id: 'docA', tenant_id: 'tenantA'})
        MERGE (ca:Chunk {id: 'chunkA', document_id: 'docA', tenant_id: 'tenantA'})
        MERGE (ea:Entity {name: 'EntityA', tenant_id: 'tenantA'})
        MERGE (da)-[:HAS_CHUNK]->(ca)-[:MENTIONS]->(ea)

        MERGE (db:Document {id: 'docB', tenant_id: 'tenantB'})
        MERGE (cb:Chunk {id: 'chunkB', document_id: 'docB', tenant_id: 'tenantB'})
        MERGE (eb:Entity {name: 'EntityB', tenant_id: 'tenantB'})
        MERGE (db)-[:HAS_CHUNK]->(cb)-[:MENTIONS]->(eb)
        """
        await neo4j_client.execute_write(setup_query)

        # 2. Test Tenant Isolation
        print("Testing Tenant Isolation...")
        acl_query = graph_acl.security_pattern("tenantA", variable_name="e")
        query = f"{acl_query} RETURN e.name as name"
        res = await neo4j_client.execute_read(query, {"tenant_id": "tenantA"})
        names = [r['name'] for r in res]
        print(f"Tenant A Query Result: {names}")

        if 'EntityA' in names and 'EntityB' not in names:
            print("✅ Tenant Isolation Passed")
        else:
            print(f"❌ Tenant Isolation Failed. Expected ['EntityA'], got {names}")

        # 3. Test Doc-Level Path ACL (e.g. User in Tenant A but only has access to docA? Or restricted?)
        print("Testing Path-Based ACL...")
        # Scenario: User has access to docA, should see EntityA
        acl_pattern = graph_acl.security_pattern("tenantA", allowed_doc_ids=['docA'], variable_name="e")
        query = f"{acl_pattern} RETURN e.name as name"
        params = {"tenant_id": "tenantA", "allowed_doc_ids": ["docA"]}

        res = await neo4j_client.execute_read(query, params)
        names = [r['name'] for r in res]
        print(f"Doc Access Query Result: {names}")

        if 'EntityA' in names:
            print("✅ Path ACL Passed (Authorized)")
        else:
            print("❌ Path ACL Failed (Authorized)")

        # Scenario: User has access to empty list (or wrong doc), should NOT see EntityA
        acl_pattern_fail = graph_acl.security_pattern("tenantA", allowed_doc_ids=['docX'], variable_name="e")
        query_fail = f"{acl_pattern_fail} RETURN e.name as name"
        params_fail = {"tenant_id": "tenantA", "allowed_doc_ids": ["docX"]}

        res_fail = await neo4j_client.execute_read(query_fail, params_fail)
        names_fail = [r['name'] for r in res_fail]

        if not names_fail:
             print("✅ Path ACL Passed (Unauthorized)")
        else:
             print(f"❌ Path ACL Failed (Unauthorized). Result: {names_fail}")

    except Exception as e:
        print(f"Integration Test Failed: {e}")
    finally:
        # Cleanup
        await neo4j_client.execute_write(clear_query)
        await neo4j_client.close()

if __name__ == "__main__":
    asyncio.run(verify_isolation())
