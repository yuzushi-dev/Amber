"""Community embeddings of vanished communities must be garbage-collected.

Every full detection mints new community ids and maintenance prunes delete nodes, but
the rows in ``community_embeddings`` were never removed; global search reads summaries
straight from that collection (7.6k of 8.5k rows were orphans on a production tenant).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.graph.application.communities.embeddings import CommunityEmbeddingService
from src.workers import tasks
from src.workers.tasks import (
    _gc_community_embeddings,
    _process_communities_async,
    _still_owns_lock,
    process_communities,
)


def _graph(rows):
    return SimpleNamespace(execute_read=AsyncMock(return_value=rows))


def _svc():
    return SimpleNamespace(prune_orphan_embeddings=AsyncMock(return_value=3))


ROWS = [
    {"id": "new1", "active": True, "generation_id": "gen-new"},
    {"id": "new2", "active": True, "generation_id": "gen-new"},
    {"id": "old1", "active": False, "generation_id": "gen-old"},
    {"id": "comm_0_misc", "active": False, "generation_id": None},  # generation-less misc
    {"id": "legacy", "active": True, "generation_id": None},
]


# --- keep-set rules ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_run_drops_only_superseded_generations_and_keeps_misc():
    svc = _svc()
    graph = _graph(ROWS)

    n = await _gc_community_embeddings(
        graph, svc, "tenant-1", activated_generation_id="gen-new", embedded_ids={"new1", "new2"}
    )

    assert n == 3
    svc.prune_orphan_embeddings.assert_awaited_once_with(
        "tenant-1", {"new1", "new2", "comm_0_misc", "legacy"}
    )
    query, params = graph.execute_read.await_args.args
    assert "coalesce(c.active, true) AS active" in query
    assert "c.generation_id AS generation_id" in query
    assert params == {"tenant_id": "tenant-1"}


@pytest.mark.asyncio
async def test_incremental_run_keeps_every_existing_community():
    svc = _svc()
    await _gc_community_embeddings(
        _graph(ROWS), svc, "tenant-1", activated_generation_id=None, embedded_ids={"new1"}
    )
    svc.prune_orphan_embeddings.assert_awaited_once_with(
        "tenant-1", {"new1", "new2", "old1", "comm_0_misc", "legacy"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rows", "embedded"),
    [
        ([], set()),  # empty read: never wipe the collection
        (ROWS, {"new1", "missing"}),  # a just-embedded community is not in the keep set
    ],
)
async def test_gc_skips_when_the_keep_set_looks_wrong(rows, embedded):
    svc = _svc()
    n = await _gc_community_embeddings(
        _graph(rows), svc, "tenant-1", activated_generation_id="gen-new", embedded_ids=embedded
    )
    assert n == 0
    svc.prune_orphan_embeddings.assert_not_awaited()


@pytest.mark.parametrize(
    ("stored", "owns"),
    [(b"run-1", True), ("run-1", True), (b"run-2", False), (None, False), (RuntimeError(), False)],
)
def test_still_owns_lock(stored, owns):
    client = MagicMock()
    if isinstance(stored, Exception):
        client.get.side_effect = stored
    else:
        client.get.return_value = stored
    assert _still_owns_lock(client, "locks:x", "run-1") is owns


# --- wiring in the community run ------------------------------------------------


async def _run(reconcile, *, skip_detection=False, gc_side_effect=None):
    calls = []
    settings = MagicMock()
    settings.db.database_url = "postgresql://test"
    settings.db.redis_url = "redis://test"
    settings.default_embedding_provider = "openai"
    settings.default_embedding_model = "text-embedding-3-small"
    settings.embedding_dimensions = 1536
    settings.community_summarization_concurrency = 1
    platform = MagicMock()
    platform.neo4j_client.execute_read = AsyncMock(return_value=[{"id": "c1"}])
    platform.neo4j_client.close = AsyncMock()
    tuning_service = MagicMock()
    tuning_service.get_effective_tenant_config = AsyncMock(return_value={})
    provider_factory = MagicMock()
    provider_factory.get_embedding_provider.return_value = MagicMock(provider_name="openai")
    detector = MagicMock()
    detector.detect_communities = AsyncMock(
        return_value={"status": "success", "community_count": 1, "generation_id": "gen-1"}
    )
    detector.assign_orphans_and_mark_stale = AsyncMock(
        return_value={"assigned": 0, "unassigned": 0}
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
    gc = AsyncMock(side_effect=gc_side_effect or (lambda *a, **k: calls.append("gc") or 0))

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
        patch.object(tasks, "_gc_community_embeddings", gc),
    ):
        result = await _process_communities_async(
            "tenant-1", skip_detection=skip_detection, reconcile_embeddings=reconcile
        )
    return result, calls, gc


@pytest.mark.asyncio
async def test_full_run_gc_happens_after_activation_with_the_activated_generation():
    result, calls, gc = await _run(lambda: True)
    assert result["status"] == "success"
    assert calls == ["embed", "activate", "gc"]
    kwargs = gc.await_args.kwargs
    assert kwargs["activated_generation_id"] == "gen-1"
    assert kwargs["embedded_ids"] == {"c1"}


@pytest.mark.asyncio
async def test_incremental_run_gc_has_no_activated_generation():
    _, calls, gc = await _run(lambda: True, skip_detection=True)
    assert calls == ["embed", "gc"]
    assert gc.await_args.kwargs["activated_generation_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reconcile", [None, lambda: False])  # no lock / lock lost by now
async def test_no_gc_without_owning_the_lock_at_prune_time(reconcile):
    _, calls, gc = await _run(reconcile)
    assert "gc" not in calls
    gc.assert_not_awaited()


@pytest.mark.asyncio
async def test_gc_failure_never_fails_the_run():
    result, _, gc = await _run(lambda: True, gc_side_effect=RuntimeError("neo4j down"))
    assert result["status"] == "success"
    gc.assert_awaited_once()


def _reconcile_arg(redis_patch):
    task = MagicMock()
    task.request.id = "community-run-1"
    pipeline = MagicMock(return_value="coro")
    with (
        redis_patch,
        patch("src.workers.tasks._is_revoked", return_value=False),
        patch("src.workers.tasks.deep_reset_singletons"),
        patch.object(tasks, "_process_communities_async", pipeline),
        patch("src.workers.tasks.run_async", return_value={"status": "success"}),
    ):
        process_communities._orig_run.__func__(task, "tenant-1")
    return pipeline.call_args.kwargs["reconcile_embeddings"]


def test_task_passes_a_lock_check_only_when_the_lock_was_acquired():
    client = MagicMock()
    client.set.return_value = True
    client.get.return_value = b"community-run-1"
    check = _reconcile_arg(patch("redis.Redis.from_url", return_value=client))
    assert callable(check) and check() is True
    client.get.return_value = b"another-run"  # lock expired and re-taken
    assert check() is False

    # Redis down: the task proceeds without a lock, so no GC at all
    assert _reconcile_arg(patch("redis.Redis.from_url", side_effect=RuntimeError("down"))) is None


# --- service and store --------------------------------------------------------------


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
