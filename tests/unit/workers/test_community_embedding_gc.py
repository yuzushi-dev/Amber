"""Community embeddings of vanished communities must be garbage-collected.

Every full detection mints new community ids and maintenance prunes delete nodes, but
the rows in ``community_embeddings`` were never removed; global search reads summaries
straight from that collection (7.6k of 8.5k rows were orphans on a production tenant).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.graph.application.communities.embeddings import CommunityEmbeddingService
from src.workers.tasks import _process_communities_async, process_communities

KEEP_QUERY_MARK = "WHERE coalesce(c.active, true) = true\n                    RETURN c.id AS id"


async def _run_full(reconcile, keep_rows):
    calls = []
    settings = MagicMock()
    settings.db.database_url = "postgresql://test"
    settings.db.redis_url = "redis://test"
    settings.default_embedding_provider = "openai"
    settings.default_embedding_model = "text-embedding-3-small"
    settings.embedding_dimensions = 1536
    settings.community_summarization_concurrency = 1
    platform = MagicMock()

    async def execute_read(query, params):
        if KEEP_QUERY_MARK in query:
            calls.append("read_keep")
            return keep_rows
        return []

    platform.neo4j_client.execute_read = AsyncMock(side_effect=execute_read)
    platform.neo4j_client.close = AsyncMock()
    tuning_service = MagicMock()
    tuning_service.get_effective_tenant_config = AsyncMock(return_value={})
    provider_factory = MagicMock()
    provider_factory.get_embedding_provider.return_value = MagicMock(provider_name="openai")
    detector = MagicMock()
    detector.detect_communities = AsyncMock(
        return_value={"status": "success", "community_count": 1, "generation_id": "gen-1"}
    )
    detector.activate_generation = AsyncMock(side_effect=lambda *a: calls.append("activate"))
    detector.discard_generation = AsyncMock()
    summarizer = MagicMock()
    summarizer.summarize_all_stale = AsyncMock()
    embedding_service = MagicMock()
    embedding_service.sync_stale_communities = AsyncMock(
        side_effect=lambda *a, **k: (
            calls.append("embed")
            or SimpleNamespace(
                ready=1, candidates=1, skipped_current=0, embedded=1, batches=1, cancelled=False
            )
        )
    )
    embedding_service.prune_orphan_embeddings = AsyncMock(
        side_effect=lambda *a: calls.append("prune") or 0
    )

    with (
        patch("src.amber_platform.composition_root.platform", platform),
        patch(
            "src.amber_platform.composition_root.build_vector_store_factory",
            return_value=lambda *_args, **_kwargs: MagicMock(),
        ),
        patch("src.api.config.settings", settings),
        patch("src.shared.kernel.runtime.configure_settings"),
        patch("src.core.database.session.configure_database"),
        patch(
            "src.core.admin_ops.application.tuning_service.TuningService",
            return_value=tuning_service,
        ),
        patch("src.core.database.session.get_session_maker"),
        patch(
            "src.core.generation.infrastructure.providers.factory.ProviderFactory",
            return_value=provider_factory,
        ),
        patch(
            "src.core.graph.application.communities.leiden.CommunityDetector",
            return_value=detector,
        ),
        patch(
            "src.core.graph.application.communities.summarizer.CommunitySummarizer",
            return_value=summarizer,
        ),
        patch("src.core.retrieval.application.embeddings_service.EmbeddingService"),
        patch(
            "src.core.graph.application.communities.embeddings.CommunityEmbeddingService",
            return_value=embedding_service,
        ),
    ):
        result = await _process_communities_async("tenant-1", reconcile_embeddings=reconcile)
    return result, calls, embedding_service


@pytest.mark.asyncio
async def test_gc_runs_after_the_new_generation_is_activated():
    result, calls, svc = await _run_full(True, [{"id": "c1"}, {"id": "c2"}])

    assert result["status"] == "success"
    assert calls == ["embed", "activate", "read_keep", "prune"]
    svc.prune_orphan_embeddings.assert_awaited_once_with("tenant-1", {"c1", "c2"})


@pytest.mark.asyncio
async def test_gc_is_off_unless_requested():
    _, calls, svc = await _run_full(False, [{"id": "c1"}])
    assert "prune" not in calls
    svc.prune_orphan_embeddings.assert_not_awaited()


@pytest.mark.asyncio
async def test_gc_never_runs_on_an_empty_keep_set():
    _, calls, svc = await _run_full(True, [])
    assert calls == ["embed", "activate", "read_keep"]
    svc.prune_orphan_embeddings.assert_not_awaited()


def _capture_reconcile(redis_patch):
    task = MagicMock()
    task.request.id = "community-run-1"
    captured = {}

    def run_async(coro):
        captured["reconcile"] = coro.cr_frame.f_locals["reconcile_embeddings"]
        coro.close()
        return {"status": "success"}

    with (
        redis_patch,
        patch("src.workers.tasks._is_revoked", return_value=False),
        patch("src.workers.tasks.deep_reset_singletons"),
        patch("src.workers.tasks.run_async", side_effect=run_async),
    ):
        process_communities._orig_run.__func__(task, "tenant-1")
    return captured["reconcile"]


def test_gc_enabled_only_when_the_tenant_lock_is_really_held():
    client = MagicMock()
    client.set.return_value = True
    client.get.return_value = b"community-run-1"
    assert _capture_reconcile(patch("redis.Redis.from_url", return_value=client)) is True

    # Redis down: the task proceeds without a lock, so another run may be staging
    assert (
        _capture_reconcile(patch("redis.Redis.from_url", side_effect=RuntimeError("down"))) is False
    )


@pytest.mark.asyncio
async def test_prune_orphan_embeddings_deletes_only_rows_outside_keep_set():
    ids = ["c1", "old1", "c2"] + [f"old{i}" for i in range(2, 1002)]
    store = SimpleNamespace(
        list_chunk_ids=AsyncMock(return_value=ids), delete_chunks=AsyncMock(return_value=1)
    )
    svc = CommunityEmbeddingService.__new__(CommunityEmbeddingService)
    svc.vector_store = store

    deleted = await svc.prune_orphan_embeddings("tenant-1", {"c1", "c2"})

    assert deleted == 1001
    batches = [c.args[0] for c in store.delete_chunks.await_args_list]
    assert [len(b) for b in batches] == [500, 500, 1]
    assert not {"c1", "c2"} & set(sum(batches, []))
    assert all(c.args[1] == "tenant-1" for c in store.delete_chunks.await_args_list)

    svc.vector_store = SimpleNamespace(delete_chunks=AsyncMock())  # no listing capability
    assert await svc.prune_orphan_embeddings("tenant-1", {"c1"}) == 0


@pytest.mark.asyncio
async def test_milvus_list_chunk_ids_reads_ids_only_and_closes_the_iterator():
    from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore

    iterator = MagicMock()
    iterator.next.side_effect = [[{"chunk_id": "a"}, {"chunk_id": "b"}], [{"chunk_id": "c"}], []]
    store = MilvusVectorStore.__new__(MilvusVectorStore)
    store.connect = AsyncMock()
    store._collection = MagicMock()
    store._collection.query_iterator.return_value = iterator

    assert await store.list_chunk_ids("tenant-1") == ["a", "b", "c"]
    kwargs = store._collection.query_iterator.call_args.kwargs
    assert kwargs["expr"] == 'tenant_id == "tenant-1"'
    assert kwargs["output_fields"] == ["chunk_id"]
    iterator.close.assert_called_once()
