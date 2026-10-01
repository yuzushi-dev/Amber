from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.graph.application.communities.embeddings import CommunityEmbeddingService


@pytest.fixture
def embedding_service():
    service = MagicMock()

    async def embed_texts(texts, **_kwargs):
        return [[0.1, 0.2, 0.3] for _ in texts], None

    service.embed_texts = AsyncMock(side_effect=embed_texts)
    return service


@pytest.fixture
def vector_store():
    store = MagicMock()
    store.upsert_chunks = AsyncMock()
    return store


@pytest.fixture
def graph_client():
    client = MagicMock()
    client.execute_write = AsyncMock()
    return client


def community(community_id: str, title: str = "Title", summary: str = "Summary") -> dict:
    return {
        "id": community_id,
        "tenant_id": "tenant-1",
        "level": 0,
        "title": title,
        "summary": summary,
    }


def make_service(embedding_service, vector_store):
    return CommunityEmbeddingService(embedding_service, vector_store)


@pytest.mark.asyncio
async def test_noop_incremental_skips_current_community(
    embedding_service, vector_store, graph_client
):
    service = make_service(embedding_service, vector_store)
    current = community("comm-current")
    current["embedding_content_hash"] = service.embedding_marker(
        current, provider="openai", model="text-embedding-3-small", dimensions=3
    )

    stats = await service.sync_stale_communities(
        [current],
        graph_client=graph_client,
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
    )

    assert stats.candidates == 0
    assert stats.skipped_current == 1
    embedding_service.embed_texts.assert_not_awaited()
    vector_store.upsert_chunks.assert_not_awaited()
    graph_client.execute_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_summary_embeds_only_that_community(
    embedding_service, vector_store, graph_client
):
    service = make_service(embedding_service, vector_store)
    current = community("comm-current")
    current["embedding_content_hash"] = service.embedding_marker(
        current, provider="openai", model="text-embedding-3-small", dimensions=3
    )
    changed = community("comm-changed", summary="New summary")
    changed["embedding_content_hash"] = current["embedding_content_hash"]

    stats = await service.sync_stale_communities(
        [current, changed],
        graph_client=graph_client,
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
    )

    assert stats.embedded == 1
    assert stats.skipped_current == 1
    assert embedding_service.embed_texts.await_args.args == (["Title: New summary"],)
    payload = vector_store.upsert_chunks.await_args.args[0]
    assert [item["chunk_id"] for item in payload] == ["comm-changed"]


def test_new_community_without_marker_is_selected(embedding_service, vector_store):
    service = make_service(embedding_service, vector_store)

    selection = service.select_stale_communities(
        [community("comm-new")], provider="openai", model="text-embedding-3-small", dimensions=3
    )

    assert [item["id"] for item in selection.communities] == ["comm-new"]


@pytest.mark.parametrize(
    ("provider", "model", "dimensions"),
    [
        ("openai", "text-embedding-3-large", 3),
        ("openai", "text-embedding-3-small", 4),
        ("ollama", "text-embedding-3-small", 3),
    ],
)
def test_embedding_identity_change_invalidates_marker(
    embedding_service, vector_store, provider, model, dimensions
):
    service = make_service(embedding_service, vector_store)
    current = community("comm-current")
    current["embedding_content_hash"] = service.embedding_marker(
        current, provider="openai", model="text-embedding-3-small", dimensions=3
    )

    selection = service.select_stale_communities(
        [current], provider=provider, model=model, dimensions=dimensions
    )

    assert [item["id"] for item in selection.communities] == ["comm-current"]


@pytest.mark.asyncio
async def test_partial_failure_retry_skips_batches_already_marked(
    embedding_service, vector_store, graph_client
):
    service = make_service(embedding_service, vector_store)
    communities = [community("comm-1"), community("comm-2")]
    vector_store.upsert_chunks.side_effect = [None, RuntimeError("Milvus unavailable")]

    with pytest.raises(RuntimeError, match="Milvus unavailable"):
        await service.sync_stale_communities(
            communities,
            graph_client=graph_client,
            provider="openai",
            model="text-embedding-3-small",
            dimensions=3,
            batch_size=1,
        )

    assert graph_client.execute_write.await_count == 1
    first_marker = graph_client.execute_write.await_args.args[1]["communities"][0]
    communities[0]["embedding_content_hash"] = first_marker["embedding_content_hash"]
    vector_store.upsert_chunks.side_effect = None
    vector_store.upsert_chunks.reset_mock()
    graph_client.execute_write.reset_mock()

    stats = await service.sync_stale_communities(
        communities,
        graph_client=graph_client,
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        batch_size=1,
    )

    assert stats.embedded == 1
    assert stats.skipped_current == 1
    assert vector_store.upsert_chunks.await_count == 1
    assert graph_client.execute_write.await_count == 1


@pytest.mark.asyncio
async def test_force_full_resync_embeds_current_communities(
    embedding_service, vector_store, graph_client
):
    service = make_service(embedding_service, vector_store)
    current = community("comm-current")
    current["embedding_content_hash"] = service.embedding_marker(
        current, provider="openai", model="text-embedding-3-small", dimensions=3
    )

    stats = await service.sync_stale_communities(
        [current],
        graph_client=graph_client,
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        force_full_resync=True,
        force_full_resync_id="resync-1",
    )

    assert stats.candidates == 1
    assert stats.embedded == 1
    assert stats.skipped_current == 0
    vector_store.upsert_chunks.assert_awaited_once()
    graph_client.execute_write.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_full_resync_retry_skips_batches_acknowledged_by_its_run(
    embedding_service, vector_store, graph_client
):
    service = make_service(embedding_service, vector_store)
    communities = [community("comm-1"), community("comm-2")]
    for item in communities:
        item["embedding_content_hash"] = service.embedding_marker(
            item, provider="openai", model="text-embedding-3-small", dimensions=3
        )
    vector_store.upsert_chunks.side_effect = [None, RuntimeError("Milvus unavailable")]

    with pytest.raises(RuntimeError, match="Milvus unavailable"):
        await service.sync_stale_communities(
            communities,
            graph_client=graph_client,
            provider="openai",
            model="text-embedding-3-small",
            dimensions=3,
            force_full_resync=True,
            force_full_resync_id="resync-1",
            batch_size=1,
        )

    first = graph_client.execute_write.await_args.args[1]["communities"][0]
    communities[0]["embedding_resync_run_id"] = "resync-1"
    assert first["id"] == "comm-1"
    vector_store.upsert_chunks.side_effect = None
    vector_store.upsert_chunks.reset_mock()
    graph_client.execute_write.reset_mock()

    stats = await service.sync_stale_communities(
        communities,
        graph_client=graph_client,
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        force_full_resync=True,
        force_full_resync_id="resync-1",
        batch_size=1,
    )

    assert stats.embedded == 1
    assert stats.skipped_current == 1
    payload = vector_store.upsert_chunks.await_args.args[0]
    assert [item["chunk_id"] for item in payload] == ["comm-2"]


@pytest.mark.asyncio
async def test_each_batch_is_embedded_with_one_dense_and_one_sparse_call(
    embedding_service, vector_store, graph_client
):
    sparse = MagicMock()
    sparse.embed_batch = MagicMock(side_effect=lambda texts: [{i: 1.0} for i in range(len(texts))])
    service = CommunityEmbeddingService(embedding_service, vector_store, sparse)
    communities = [community(f"comm-{i}", summary=f"S{i}") for i in range(5)]

    stats = await service.sync_stale_communities(
        communities,
        graph_client=graph_client,
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        batch_size=2,
    )

    assert stats.embedded == 5 and stats.batches == 3
    assert [len(c.args[0]) for c in embedding_service.embed_texts.await_args_list] == [2, 2, 1]
    assert [len(c.args[0]) for c in sparse.embed_batch.call_args_list] == [2, 2, 1]
    payloads = [p for c in vector_store.upsert_chunks.await_args_list for p in c.args[0]]
    assert [p["chunk_id"] for p in payloads] == [f"comm-{i}" for i in range(5)]
    assert all(p["sparse_vector"] and p["embedding"] == [0.1, 0.2, 0.3] for p in payloads)


@pytest.mark.asyncio
async def test_a_time_limit_during_sparse_embedding_is_not_swallowed(
    embedding_service, vector_store, graph_client, monkeypatch
):
    from celery.exceptions import SoftTimeLimitExceeded

    from src.core.retrieval.application import sparse_embeddings_service as sparse_module

    sparse = sparse_module.SparseEmbeddingService.__new__(sparse_module.SparseEmbeddingService)
    monkeypatch.setattr(sparse, "_load_model", lambda: None, raising=False)

    def tokenizer(*_a, **_k):
        raise SoftTimeLimitExceeded()

    sparse._tokenizer = tokenizer
    sparse._device = "cpu"
    service = CommunityEmbeddingService(embedding_service, vector_store, sparse)

    with pytest.raises(SoftTimeLimitExceeded):
        await service.sync_stale_communities(
            [community("comm-1")],
            graph_client=graph_client,
            provider="openai",
            model="text-embedding-3-small",
            dimensions=3,
        )
    vector_store.upsert_chunks.assert_not_awaited()


def test_community_task_time_limits_cover_a_full_run_and_the_lock_outlives_them():
    import inspect

    from src.workers import tasks

    assert tasks.process_communities.soft_time_limit == tasks.COMMUNITY_SOFT_TIME_LIMIT
    assert tasks.process_communities.time_limit == tasks.COMMUNITY_TIME_LIMIT
    assert tasks.COMMUNITY_SOFT_TIME_LIMIT > 3600
    assert tasks.COMMUNITY_TIME_LIMIT > tasks.COMMUNITY_SOFT_TIME_LIMIT
    source = inspect.getsource(tasks.process_communities._orig_run)
    assert "lock_ttl_seconds = COMMUNITY_TIME_LIMIT +" in source
