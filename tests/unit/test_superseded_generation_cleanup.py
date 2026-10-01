"""After a generation is published, the superseded generations' vectors and graph
artifacts must be removed (they used to be only hidden and accumulated: 68% of the
vector collection and ~17k unpublished graph chunks on a production corpus), without
ever touching an in-flight (staging) generation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.graph.infrastructure.neo4j_client import Neo4jClient
from src.core.ingestion.application import ingestion_service as service_module


class _Noop:
    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def _lightweight_service(monkeypatch):
    monkeypatch.setattr(service_module, "SemanticChunker", _Noop)
    monkeypatch.setattr(service_module, "EmbeddingService", _Noop)
    monkeypatch.setattr(service_module, "GraphProcessor", _Noop)


def _service(repo, neo4j):
    return service_module.IngestionService(
        document_repository=repo,
        tenant_repository=None,
        unit_of_work=None,
        storage_client=None,
        neo4j_client=neo4j,
        vector_store=None,
    )


# --- service ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_deletes_superseded_vectors_in_batches_and_graph():
    old_ids = [f"chunk_old_{i:05d}" for i in range(1200)]
    repo = SimpleNamespace(get_superseded_artifacts=AsyncMock(return_value=(["gen-old"], old_ids)))
    neo4j = SimpleNamespace(delete_superseded_generation=AsyncMock(return_value={"chunks": 3}))
    vectors = SimpleNamespace(delete_chunks=AsyncMock(return_value=500))

    await _service(repo, neo4j)._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )

    repo.get_superseded_artifacts.assert_awaited_once_with("doc-1", "gen-new")
    batches = [c.args[0] for c in vectors.delete_chunks.await_args_list]
    assert [len(b) for b in batches] == [500, 500, 200]
    assert sum(batches, []) == old_ids
    assert all(c.args[1] == "tenant-1" for c in vectors.delete_chunks.await_args_list)
    neo4j.delete_superseded_generation.assert_awaited_once_with("doc-1", "tenant-1", ["gen-old"])


@pytest.mark.asyncio
async def test_cleanup_skips_everything_when_the_published_generation_changed():
    repo = SimpleNamespace(get_superseded_artifacts=AsyncMock(return_value=None))
    neo4j = SimpleNamespace(delete_superseded_generation=AsyncMock())
    vectors = SimpleNamespace(delete_chunks=AsyncMock())

    await _service(repo, neo4j)._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )

    vectors.delete_chunks.assert_not_awaited()
    neo4j.delete_superseded_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_failures_are_swallowed_and_independent():
    repo = SimpleNamespace(get_superseded_artifacts=AsyncMock(return_value=([], ["chunk_old"])))
    neo4j = SimpleNamespace(
        delete_superseded_generation=AsyncMock(side_effect=RuntimeError("neo4j"))
    )
    vectors = SimpleNamespace(delete_chunks=AsyncMock(side_effect=RuntimeError("milvus")))

    await _service(repo, neo4j)._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )

    vectors.delete_chunks.assert_awaited_once()
    neo4j.delete_superseded_generation.assert_awaited_once()

    failing_lookup = SimpleNamespace(get_superseded_artifacts=AsyncMock(side_effect=RuntimeError()))
    await _service(failing_lookup, neo4j)._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )


@pytest.mark.asyncio
async def test_cleanup_without_old_chunks_or_capabilities_is_a_noop():
    repo = SimpleNamespace(get_superseded_artifacts=AsyncMock(return_value=([], [])))
    neo4j = SimpleNamespace(delete_superseded_generation=AsyncMock())
    vectors = SimpleNamespace(delete_chunks=AsyncMock())
    await _service(repo, neo4j)._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )
    vectors.delete_chunks.assert_not_awaited()
    neo4j.delete_superseded_generation.assert_not_awaited()

    await _service(object(), object())._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", None
    )


@pytest.mark.asyncio
async def test_cleanup_runs_only_after_a_successful_graph_promotion():
    neo4j = SimpleNamespace(publish_document_generation=AsyncMock(side_effect=RuntimeError()))
    service = _service(object(), neo4j)
    service._delete_superseded_generation_artifacts = AsyncMock()

    await service._promote_generation_and_cleanup("doc-1", "tenant-1", "gen-new", None)
    service._delete_superseded_generation_artifacts.assert_not_awaited()

    neo4j.publish_document_generation = AsyncMock()
    await service._promote_generation_and_cleanup("doc-1", "tenant-1", "gen-new", "vs")
    neo4j.publish_document_generation.assert_awaited_once_with("doc-1", "tenant-1", "gen-new")
    service._delete_superseded_generation_artifacts.assert_awaited_once_with(
        "doc-1", "tenant-1", "gen-new", "vs"
    )


def test_process_document_uses_the_guarded_promotion():
    import inspect

    source = inspect.getsource(service_module.IngestionService.process_document)
    assert "_promote_generation_and_cleanup(" in source
    assert "publish_document_generation(" not in source


# --- Neo4j ----------------------------------------------------------------------


class _FakeTx:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def run(self, query, params):
        self.calls.append((query, params))
        value = self.results.pop(0)
        return SimpleNamespace(single=AsyncMock(return_value=[value]))


@pytest.mark.asyncio
async def test_graph_cleanup_is_one_transaction_scoped_to_superseded_generations():
    tx = _FakeTx([["4:e:1", "4:e:2"], 7, 5, 1])

    async def _execute_write(fn):  # the driver awaits the transaction function
        return await fn(tx)

    session = SimpleNamespace(execute_write=AsyncMock(side_effect=_execute_write))

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    client = Neo4jClient.__new__(Neo4jClient)
    client.get_driver = AsyncMock(return_value=SimpleNamespace(session=lambda: _Ctx()))

    counts = await client.delete_superseded_generation("doc-1", "tenant-1", ["gen-old"])

    assert counts == {"chunks": 5, "relationships": 7, "entities": 1}
    session.execute_write.assert_awaited_once()  # a single write transaction
    (cand_q, cand_p), (rel_q, rel_p), (chunk_q, _), (ent_q, ent_p) = tx.calls
    for q in (cand_q, chunk_q):
        assert "{document_id: $document_id, tenant_id: $tenant_id}" in q
        assert "old.generation_id IS NULL OR old.generation_id IN $old" in q
        assert "<>" not in q  # never "everything but the new one": staging stays safe
    assert cand_p["old"] == ["gen-old"]
    # relationships: only the superseded generations', reached from candidate entities
    assert "elementId(e) IN $entity_ids" in rel_q
    assert "r.document_id = $document_id AND r.generation_id IN $old" in rel_q
    assert rel_p["entity_ids"] == ["4:e:1", "4:e:2"]
    assert "DETACH DELETE old" in chunk_q
    # entities: only candidates with no mention and no entity relationship left
    assert "NOT EXISTS { MATCH (:Chunk)-[:MENTIONS]->(e) }" in ent_q
    assert "MATCH (e)-[x]-(:Entity) WHERE NOT type(x) IN ['BELONGS_TO', 'PARENT_OF']" in ent_q
    assert "c.is_stale = true" in ent_q
    assert ent_p == {"tenant_id": "tenant-1", "entity_ids": ["4:e:1", "4:e:2"]}


# --- Postgres -------------------------------------------------------------------


def _rows(*rows):
    return SimpleNamespace(first=lambda: rows[0] if rows else None, all=lambda: list(rows))


@pytest.mark.asyncio
async def test_superseded_artifacts_exclude_staging_and_pending_generations():
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )

    doc = SimpleNamespace(active_generation_id="gen-new", pending_generation_id="gen-inflight")
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_rows(doc), _rows(("gen-old",)), _rows(("chunk_a",), ("chunk_b",))]
        )
    )
    repo = PostgresDocumentRepository(session)

    result = await repo.get_superseded_artifacts("doc-1", "gen-new")

    assert result == (["gen-old"], ["chunk_a", "chunk_b"])

    def sql(i):
        stmt = session.execute.await_args_list[i].args[0]
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))

    gens_sql = sql(1)
    assert "document_generations.status = 'published'" in gens_sql
    assert "document_generations.id != 'gen-new'" in gens_sql
    assert "document_generations.id != 'gen-inflight'" in gens_sql
    chunks_sql = sql(2)
    assert "chunks.generation_id IS NULL OR chunks.generation_id IN ('gen-old')" in chunks_sql


@pytest.mark.asyncio
async def test_superseded_artifacts_none_when_generation_is_no_longer_active():
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )

    doc = SimpleNamespace(active_generation_id="gen-newer", pending_generation_id=None)
    session = SimpleNamespace(execute=AsyncMock(side_effect=[_rows(doc)]))

    repo = PostgresDocumentRepository(session)
    assert await repo.get_superseded_artifacts("doc-1", "gen-new") is None
    assert session.execute.await_count == 1
