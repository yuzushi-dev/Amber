"""Opt-in graph transaction check on a disposable local Neo4j 5 server."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from neo4j.exceptions import ClientError

from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.ingestion.application.use_cases_documents import (
    DeleteDocumentRequest,
    DeleteDocumentUseCase,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize("graph_document_exists", [True, False])
async def test_real_graph_delete_is_atomic_and_retriable(graph_document_exists):
    uri = os.environ.get("AMBER_TEST_NEO4J_URI")
    if uri not in {"bolt://127.0.0.1:17687", "bolt://localhost:7688"}:
        pytest.skip("Requires disposable local Neo4j (port 17687 or CI port 7688)")
    graph = Neo4jClient(uri, "neo4j", os.environ.get("AMBER_TEST_NEO4J_PASSWORD", "unused"))
    tenant = str(uuid4())
    params = {"tenant": tenant}
    document = SimpleNamespace(
        processing_attempt_id=None, tenant_id=tenant, storage_path="test/source"
    )
    row = Mock(scalars=Mock(return_value=Mock(first=Mock(return_value=document))))
    generations = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[]))))
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[row, generations] * 2),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )
    vectors = SimpleNamespace(delete_by_document=AsyncMock(), disconnect=AsyncMock())
    use_case = DeleteDocumentUseCase(session, Mock(), graph, lambda _: vectors)
    request = DeleteDocumentRequest(document_id="doc", tenant_id=tenant)
    original = graph.execute_write
    try:
        if graph_document_exists:
            await graph.execute_write(
                """CREATE (d:Document {id: 'doc', tenant_id: $tenant})
                CREATE (ch:Chunk {id: 'chunk', document_id: 'doc', tenant_id: $tenant})
                CREATE (e:Entity {id: 'removed', tenant_id: $tenant})
                CREATE (shared:Entity {id: 'shared', tenant_id: $tenant})
                CREATE (other:Chunk {id: 'other', document_id: 'other', tenant_id: $tenant})
                CREATE (c:Community {id: 'community', tenant_id: $tenant})
                CREATE (d)-[:HAS_CHUNK]->(ch)-[:MENTIONS]->(e)-[:BELONGS_TO]->(c)
                CREATE (other)-[:MENTIONS]->(shared)-[:BELONGS_TO]->(c)""",
                params,
            )

        async def fail_late(query, parameters):
            return await original(
                query.replace("RETURN marked", "RETURN 1 / 0 AS marked"), parameters
            )

        graph.execute_write = fail_late
        with pytest.raises(ClientError):
            await use_case.execute(request)
        session.delete.assert_not_awaited()
        session.commit.assert_not_awaited()
        graph.execute_write = original
        count_query = "MATCH (d:Document {id: 'doc', tenant_id: $tenant}) RETURN count(d) AS count"
        assert (await graph.execute_read(count_query, params))[0]["count"] == int(
            graph_document_exists
        )
        await use_case.execute(request)
        session.delete.assert_awaited_once_with(document)
        assert (await graph.execute_read(count_query, params))[0]["count"] == 0
        if graph_document_exists:
            communities = await graph.execute_read(
                "MATCH (c:Community {tenant_id: $tenant}) RETURN c.is_stale AS stale", params
            )
            assert communities == [{"stale": True}]
            entities = await graph.execute_read(
                "MATCH (e:Entity {tenant_id: $tenant}) RETURN e.id AS id", params
            )
            assert entities == [{"id": "shared"}]
    finally:
        graph.execute_write = original
        await graph.execute_write("MATCH (n {tenant_id: $tenant}) DETACH DELETE n", params)
        await graph.close()
