"""Pruning must be scoped, read-only by default and atomic when applied."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.graph.infrastructure.neo4j_client import Neo4jClient


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize("dry_run,candidates", [(True, 2), (False, 2), (False, 3)])
async def test_pruning_transaction_scope_and_limit(dry_run, candidates):
    client = Neo4jClient("bolt://unused", "unused", "unused")
    queries = []

    async def execute(tx, query, params):
        queries.append(query)
        assert params["tenant_id"] == "tenant-1"
        assert "tenant_id: $tenant_id" in query
        if "DETACH DELETE" in query:
            assert "elementId(n) IN $candidate_ids" in query
            assert params["candidate_ids"] == [str(i) for i in range(candidates)]
            assert params["include_all_chunks"] is True
            return [{"deleted": candidates}]
        assert params["include_all_chunks"] is False
        return [{"total": 10, "candidate_ids": [str(i) for i in range(candidates)]}]

    async def transaction(callback):
        return await callback(object())

    session = Mock()
    session.execute_read = AsyncMock(side_effect=transaction)
    session.execute_write = AsyncMock(side_effect=transaction)
    context = AsyncMock()
    context.__aenter__.return_value = session
    client.get_driver = AsyncMock(return_value=SimpleNamespace(session=Mock(return_value=context)))
    client._execute_tx = AsyncMock(side_effect=execute)

    if not dry_run and candidates == 3:
        with pytest.raises(ValueError, match="20%"):
            await client.prune_orphans(["doc"], ["chunk"], tenant_id="tenant-1", dry_run=False)
        assert not any("DETACH DELETE" in q for q in queries)
    else:
        counts = await client.prune_orphans(
            ["doc"], ["chunk"], tenant_id="tenant-1", dry_run=dry_run
        )
        assert counts == dict.fromkeys(
            ["documents", "chunks", "entities", "communities"], candidates
        )
        assert sum("DETACH DELETE" in q for q in queries) == (0 if dry_run else 4)
        assert "$valid_chunk_ids" in queries[2] and "$valid_chunk_ids" in queries[3]
        assert "IN_COMMUNITY" in queries[3]
    if dry_run:
        session.execute_write.assert_not_awaited()
    else:
        session.execute_write.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize(
    "tenant,docs,chunks", [("", ["d"], ["c"]), ("t", [], ["c"]), ("t", ["d"], [])]
)
async def test_empty_snapshot_never_opens_graph_connection(tenant, docs, chunks):
    client = Neo4jClient("bolt://unused", "unused", "unused")
    client.get_driver = AsyncMock()
    with pytest.raises(ValueError, match="non-empty"):
        await client.prune_orphans(docs, chunks, tenant_id=tenant)
    client.get_driver.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize("empty", [False, True])
async def test_route_sets_tenant_rls_before_reading_ids(monkeypatch, empty):
    import sys

    from fastapi import HTTPException

    import src.core.database.session as database
    from src.api.routes.admin.maintenance import prune_orphans

    current_tenant = None
    statements = []

    async def execute(query, params=None):
        nonlocal current_tenant
        sql = str(query)
        statements.append(sql)
        if "app.current_tenant" in sql:
            current_tenant = params["t"]
        if "SELECT id FROM tenants" in sql:
            return Mock(fetchall=Mock(return_value=[("one",), ("two",)]))
        if "SELECT documents.id" in sql or "SELECT chunks.id" in sql:
            assert current_tenant in ["one", "two"]
            assert "tenant_id" in sql
            ids = [] if empty and current_tenant == "two" else [current_tenant]
            return Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=ids))))
        return Mock()

    context = AsyncMock()
    context.__aenter__.return_value = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    monkeypatch.setattr(database, "async_session_maker", lambda: context)
    graph = SimpleNamespace(prune_orphans=AsyncMock(return_value={"documents": 1}))
    monkeypatch.setitem(
        sys.modules,
        "src.amber_platform.composition_root",
        SimpleNamespace(platform=SimpleNamespace(neo4j_client=graph)),
    )
    if empty:
        with pytest.raises(HTTPException) as exc:
            await prune_orphans(dry_run=False, tenant_id="two")
        assert exc.value.status_code == 409
        graph.prune_orphans.assert_not_awaited()
    else:
        result = await prune_orphans()
        assert result.items_affected == 2
        assert "Dry run" in result.message
        assert graph.prune_orphans.await_count == 2
        for call, tenant in zip(graph.prune_orphans.await_args_list, ["one", "two"], strict=True):
            assert call.args == ([tenant], [tenant])
            assert call.kwargs == {"tenant_id": tenant, "dry_run": True}
    assert "app.is_super_admin" in statements[0]
    assert ", true)" in statements[0]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_apply_requires_explicit_tenant():
    from fastapi import HTTPException

    from src.api.routes.admin.maintenance import prune_orphans

    with pytest.raises(HTTPException) as exc:
        await prune_orphans(dry_run=False)
    assert exc.value.status_code == 409
    assert "explicit tenant_id" in exc.value.detail
