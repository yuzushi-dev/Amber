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
    sparse.embed_batch = MagicMock(
        side_effect=lambda texts, *_a: [{i: 1.0} for i in range(len(texts))]
    )
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


def _sparse_service(tokenizer):
    from src.core.retrieval.application import sparse_embeddings_service as sparse_module

    sparse = sparse_module.SparseEmbeddingService.__new__(sparse_module.SparseEmbeddingService)
    sparse._load_model = lambda: None
    sparse._tokenizer = tokenizer
    sparse._device = "cpu"
    return sparse


def test_embed_batch_reraises_a_task_time_limit():
    from src.shared.exceptions import SoftTimeLimitExceeded

    def tokenizer(*_a, **_k):
        raise SoftTimeLimitExceeded()

    with pytest.raises(SoftTimeLimitExceeded):
        _sparse_service(tokenizer).embed_batch(["a", "b"])


def test_embed_batch_still_degrades_model_errors_to_empty_vectors():
    def tokenizer(*_a, **_k):
        raise RuntimeError("model failure")

    assert _sparse_service(tokenizer).embed_batch(["a", "b", "c"]) == [{}, {}, {}]


@pytest.mark.asyncio
async def test_a_time_limit_inside_the_sparse_thread_stops_the_sync(
    embedding_service, vector_store, graph_client
):
    from src.shared.exceptions import SoftTimeLimitExceeded

    def tokenizer(*_a, **_k):
        raise SoftTimeLimitExceeded()

    service = CommunityEmbeddingService(embedding_service, vector_store, _sparse_service(tokenizer))
    with pytest.raises(SoftTimeLimitExceeded):
        await service.sync_stale_communities(
            [community("comm-1")],
            graph_client=graph_client,
            provider="openai",
            model="text-embedding-3-small",
            dimensions=3,
        )
    vector_store.upsert_chunks.assert_not_awaited()
    graph_client.execute_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_sparse_failure_raises_a_clear_error_instead_of_a_schema_error(
    embedding_service, vector_store, graph_client
):
    def tokenizer(*_a, **_k):
        raise RuntimeError("CUDA/CPU OOM")

    service = CommunityEmbeddingService(embedding_service, vector_store, _sparse_service(tokenizer))
    with pytest.raises(RuntimeError, match="Sparse embedding failed"):
        await service.sync_stale_communities(
            [community("comm-1"), community("comm-2")],
            graph_client=graph_client,
            provider="openai",
            model="text-embedding-3-small",
            dimensions=3,
        )
    vector_store.upsert_chunks.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_dense_vectors_raise_before_upsert(vector_store, graph_client):
    dense = MagicMock()
    dense.embed_texts = AsyncMock(return_value=([[0.1, 0.2, 0.3], []], None))
    service = CommunityEmbeddingService(dense, vector_store)
    with pytest.raises(RuntimeError, match="Dense embedding returned missing vectors"):
        await service.sync_stale_communities(
            [community("comm-1"), community("comm-2")],
            graph_client=graph_client,
            provider="openai",
            model="text-embedding-3-small",
            dimensions=3,
        )
    vector_store.upsert_chunks.assert_not_awaited()


def test_community_task_time_limits_and_lock_ttl():
    from src.workers import tasks

    assert tasks.process_communities.soft_time_limit == tasks.COMMUNITY_SOFT_TIME_LIMIT > 3600
    assert tasks.process_communities.time_limit == tasks.COMMUNITY_TIME_LIMIT
    assert tasks.COMMUNITY_LOCK_TTL > tasks.COMMUNITY_TIME_LIMIT > tasks.COMMUNITY_SOFT_TIME_LIMIT


def test_the_task_takes_the_lock_with_the_ttl_constant():
    from unittest.mock import patch

    from src.workers import tasks

    task = MagicMock()
    task.request.id = "community-run-1"
    client = MagicMock()
    client.set.return_value = False  # someone else holds it: return before running
    with (
        patch("redis.Redis.from_url", return_value=client),
        patch("src.workers.tasks._is_revoked", return_value=False),
    ):
        result = tasks.process_communities._orig_run.__func__(task, "tenant-1")

    assert result["reason"] == "already_running"
    assert client.set.call_args.kwargs == {"nx": True, "ex": tasks.COMMUNITY_LOCK_TTL}


@pytest.mark.asyncio
async def test_summarizer_does_not_swallow_a_task_time_limit(monkeypatch):
    from src.core.graph.application.communities.summarizer import CommunitySummarizer
    from src.shared.exceptions import SoftTimeLimitExceeded

    summarizer = CommunitySummarizer.__new__(CommunitySummarizer)
    summarizer.graph = MagicMock()
    summarizer.graph.execute_write = AsyncMock()
    summarizer._fetch_community_data = AsyncMock(
        return_value={"entities": [{"name": "e"}], "child_summaries": []}
    )

    def time_limit(**_kwargs):  # raised inside the summarization try block
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(
        "src.core.generation.application.llm_steps.resolve_llm_step_config", time_limit
    )
    monkeypatch.setattr("src.shared.kernel.runtime.get_settings", lambda: MagicMock())

    with pytest.raises(SoftTimeLimitExceeded):
        await summarizer.summarize_community("comm-1", "tenant-1", {}, None)
    summarizer.graph.execute_write.assert_not_awaited()  # not marked as failed
