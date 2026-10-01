"""After a generation is published, the older generations' vectors and graph artifacts
must be removed (they used to be only hidden and accumulated: 68% of the vector
collection and ~17k unpublished graph chunks on a production corpus)."""

import inspect
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


@pytest.mark.asyncio
async def test_cleanup_deletes_superseded_vectors_in_batches_and_graph():
    old_ids = [f"chunk_old_{i:05d}" for i in range(1200)]
    repo = SimpleNamespace(get_superseded_chunk_ids=AsyncMock(return_value=old_ids))
    neo4j = SimpleNamespace(delete_superseded_generation=AsyncMock(return_value={"chunks": 3}))
    vectors = SimpleNamespace(delete_chunks=AsyncMock(return_value=500))

    await _service(repo, neo4j)._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )

    repo.get_superseded_chunk_ids.assert_awaited_once_with("doc-1", "gen-new")
    batches = [c.args[0] for c in vectors.delete_chunks.await_args_list]
    assert [len(b) for b in batches] == [500, 500, 200]
    assert sum(batches, []) == old_ids
    assert all(c.args[1] == "tenant-1" for c in vectors.delete_chunks.await_args_list)
    neo4j.delete_superseded_generation.assert_awaited_once_with("doc-1", "tenant-1", "gen-new")


@pytest.mark.asyncio
async def test_cleanup_failures_are_swallowed_and_independent():
    repo = SimpleNamespace(get_superseded_chunk_ids=AsyncMock(return_value=["chunk_old"]))
    neo4j = SimpleNamespace(
        delete_superseded_generation=AsyncMock(side_effect=RuntimeError("neo4j"))
    )
    vectors = SimpleNamespace(delete_chunks=AsyncMock(side_effect=RuntimeError("milvus")))

    await _service(repo, neo4j)._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )

    vectors.delete_chunks.assert_awaited_once()
    neo4j.delete_superseded_generation.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_without_old_chunks_or_capabilities_is_a_noop():
    repo = SimpleNamespace(get_superseded_chunk_ids=AsyncMock(return_value=[]))
    vectors = SimpleNamespace(delete_chunks=AsyncMock())
    await _service(repo, object())._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", vectors
    )
    vectors.delete_chunks.assert_not_awaited()

    await _service(object(), object())._delete_superseded_generation_artifacts(
        "doc-1", "tenant-1", "gen-new", None
    )


def test_cleanup_runs_only_after_a_successful_graph_promotion():
    source = inspect.getsource(service_module.IngestionService.process_document)
    promote = source.index("publish_document_generation(")
    cleanup = source.index("_delete_superseded_generation_artifacts(")
    assert promote < cleanup
    # it sits in the try/else of the promotion, not after the except branch
    between = source[promote:cleanup]
    assert "except Exception as graph_publish_error" in between
    assert "else:" in between.split("except Exception as graph_publish_error", 1)[1]


@pytest.mark.asyncio
async def test_graph_cleanup_targets_only_older_generations_of_the_document():
    client = Neo4jClient.__new__(Neo4jClient)
    client.execute_read = AsyncMock(return_value=[{"ids": ["4:e:1", "4:e:2"]}])
    client.execute_write = AsyncMock(side_effect=[[{"n": 5}], [{"n": 7}], [{"n": 1}]])

    counts = await client.delete_superseded_generation("doc-1", "tenant-1", "gen-new")

    assert counts == {"chunks": 5, "relationships": 7, "entities": 1}
    read_q, read_p = client.execute_read.await_args.args
    assert "old.generation_id IS NULL OR old.generation_id <> $generation_id" in read_q
    assert read_p == {"document_id": "doc-1", "tenant_id": "tenant-1", "generation_id": "gen-new"}

    (chunk_q, chunk_p), (rel_q, _), (ent_q, ent_p) = [
        c.args for c in client.execute_write.await_args_list
    ]
    assert "{document_id: $document_id, tenant_id: $tenant_id}" in chunk_q
    assert "old.generation_id IS NULL OR old.generation_id <> $generation_id" in chunk_q
    assert "DETACH DELETE old" in chunk_q
    # legacy relationships without generation are shared across documents: never touched
    assert "r.generation_id IS NOT NULL AND r.generation_id <> $generation_id" in rel_q
    # only candidate entities that lost every mention, stale-marking their communities
    assert "elementId(e) IN $entity_ids" in ent_q
    assert "NOT EXISTS { MATCH (:Chunk)-[:MENTIONS]->(e) }" in ent_q
    assert "c.is_stale = true" in ent_q
    assert ent_p == {"tenant_id": "tenant-1", "entity_ids": ["4:e:1", "4:e:2"]}


@pytest.mark.asyncio
async def test_superseded_chunk_ids_query_includes_legacy_rows():
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )

    result = SimpleNamespace(all=lambda: [("chunk_a",), ("chunk_b",)])
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    repo = PostgresDocumentRepository(session)

    ids = await repo.get_superseded_chunk_ids("doc-1", "gen-new")

    assert ids == ["chunk_a", "chunk_b"]
    sql = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "chunks.document_id = 'doc-1'" in sql
    assert "chunks.generation_id IS NULL OR chunks.generation_id != 'gen-new'" in sql
