from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.graph.application.communities.embeddings import CommunityEmbeddingService


@pytest.fixture
def embedding_service():
    service = MagicMock()
    service.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])
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
    embedding_service.embed_single.assert_not_awaited()
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
    assert embedding_service.embed_single.await_args.args == ("Title: New summary",)
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
    )

    assert stats.candidates == 1
    assert stats.embedded == 1
    assert stats.skipped_current == 0
    vector_store.upsert_chunks.assert_awaited_once()
    graph_client.execute_write.assert_awaited_once()
