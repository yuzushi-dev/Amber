"""Opt-in Neo4j 5 check against a disposable local test server only."""

import os
from uuid import uuid4

import pytest

from src.core.graph.infrastructure.neo4j_client import Neo4jClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_real_neo4j_preview_apply_threshold_and_rollback():
    uri = os.environ.get("AMBER_TEST_NEO4J_URI")
    if uri not in {"bolt://127.0.0.1:17687", "bolt://localhost:7688"}:
        pytest.skip("Requires disposable local Neo4j (port 17687 or CI port 7688)")
    graph = Neo4jClient(uri, "neo4j", os.environ.get("AMBER_TEST_NEO4J_PASSWORD", "unused"))
    tenant = str(uuid4())
    other = str(uuid4())
    ids = [str(i) for i in range(9)]
    params = {"tenant": tenant, "other": other}
    try:
        await graph.execute_write(
            """UNWIND range(0, 9) AS i
            CREATE (d:Document {id: toString(i), tenant_id: $tenant})
            CREATE (ch:Chunk {id: toString(i), tenant_id: $tenant})
            CREATE (e:Entity {id: toString(i), tenant_id: $tenant})
            CREATE (c:Community {id: toString(i), tenant_id: $tenant})
            CREATE (d)-[:HAS_CHUNK]->(ch)-[:MENTIONS]->(e)-[:BELONGS_TO]->(c)""",
            params,
        )
        await graph.execute_write("CREATE (:Document {id: 'other', tenant_id: $other})", params)
        expected = dict.fromkeys(["documents", "chunks", "entities", "communities"], 1)
        assert await graph.prune_orphans(ids, ids, tenant_id=tenant) == expected
        count_query = "MATCH (n {tenant_id: $tenant}) RETURN count(n) AS count"
        assert (await graph.execute_read(count_query, params))[0]["count"] == 40

        # A late failure must roll back the earlier category deletions.
        original = graph._execute_tx

        async def fail_last(tx, query, parameters):
            if "DETACH DELETE" in query and "n:Community" in query:
                raise RuntimeError("late failure")
            return await original(tx, query, parameters)

        graph._execute_tx = fail_last
        with pytest.raises(RuntimeError, match="late failure"):
            await graph.prune_orphans(ids, ids, tenant_id=tenant, dry_run=False)
        graph._execute_tx = original
        assert (await graph.execute_read(count_query, params))[0]["count"] == 40

        assert await graph.prune_orphans(ids, ids, tenant_id=tenant, dry_run=False) == expected
        assert (await graph.execute_read(count_query, params))[0]["count"] == 36
        assert (
            await graph.execute_read(
                "MATCH (n {tenant_id: $other}) RETURN count(n) AS count", params
            )
        )[0]["count"] == 1
        with pytest.raises(ValueError, match="20%"):
            await graph.prune_orphans(["missing"], ["missing"], tenant_id=tenant, dry_run=False)
        assert (await graph.execute_read(count_query, params))[0]["count"] == 36
    finally:
        await graph.execute_write(
            "MATCH (n) WHERE n.tenant_id IN $tenants DETACH DELETE n", {"tenants": [tenant, other]}
        )
        await graph.close()
