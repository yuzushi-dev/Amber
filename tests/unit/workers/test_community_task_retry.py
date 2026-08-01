from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers.tasks import CommunityPhaseError, _process_communities_async, process_communities


class EmbeddingPhaseFailure(RuntimeError):
    resume_from = "embedding"


class RetryRequested(Exception):
    pass


def _task() -> MagicMock:
    task = MagicMock()
    task.request.id = "community-run-1"
    return task


def _redis_client() -> MagicMock:
    client = MagicMock()
    client.get.return_value = b"community-run-1"
    return client


def _raise_embedding_failure(coro):
    coro.close()
    raise EmbeddingPhaseFailure("embedding failed")


def test_embedding_failure_retries_from_embedding_phase():
    task = _task()
    task.retry.side_effect = RetryRequested

    with (
        patch("redis.Redis.from_url", return_value=_redis_client()),
        patch("src.workers.tasks._is_revoked", return_value=False),
        patch("src.workers.tasks.deep_reset_singletons"),
        patch("src.workers.tasks.run_async", side_effect=_raise_embedding_failure),
        pytest.raises(RetryRequested),
    ):
        process_communities._orig_run.__func__(task, "tenant-1")

    assert task.retry.call_args.kwargs["kwargs"]["resume_from"] == "embedding"


def test_invalid_retry_checkpoint_never_acquires_tenant_lock():
    task = _task()

    with (
        patch("redis.Redis.from_url") as from_url,
        patch("src.workers.tasks._is_revoked", return_value=False),
        pytest.raises(ValueError, match="Unknown community resume phase"),
    ):
        process_communities._orig_run.__func__(task, "tenant-1", resume_from="invalid")

    from_url.assert_not_called()


def test_revoked_task_never_acquires_tenant_lock():
    task = _task()

    with (
        patch("redis.Redis.from_url") as from_url,
        patch("src.workers.tasks._is_revoked", return_value=True),
    ):
        result = process_communities._orig_run.__func__(task, "tenant-1")

    assert result["status"] == "cancelled"
    from_url.assert_not_called()


def test_embedding_retry_forwards_checkpoint_to_async_pipeline():
    task = _task()
    captured = {}

    def run_async(coro):
        captured["resume_from"] = coro.cr_frame.f_locals["resume_from"]
        coro.close()
        return {"status": "success"}

    with (
        patch("redis.Redis.from_url", return_value=_redis_client()),
        patch("src.workers.tasks._is_revoked", return_value=False),
        patch("src.workers.tasks.deep_reset_singletons"),
        patch("src.workers.tasks.run_async", side_effect=run_async),
    ):
        process_communities._orig_run.__func__(task, "tenant-1", resume_from="embedding")

    assert captured["resume_from"] == "embedding"


@pytest.mark.asyncio
async def test_embedding_retry_skips_detection_and_summarization():
    settings = MagicMock()
    settings.db.database_url = "postgresql://test"
    settings.db.redis_url = "redis://test"
    settings.default_embedding_provider = "openai"
    settings.default_embedding_model = "text-embedding-3-small"
    settings.embedding_dimensions = 1536
    platform = MagicMock()
    platform.neo4j_client.execute_read = AsyncMock(return_value=[])
    platform.neo4j_client.close = AsyncMock()
    tuning_service = MagicMock()
    tuning_service.get_effective_tenant_config = AsyncMock(return_value={})
    provider_factory = MagicMock()
    provider_factory.get_embedding_provider.return_value = MagicMock(provider_name="openai")
    summarizer = MagicMock()
    summarizer.summarize_all_stale = AsyncMock()
    embedding_service = MagicMock()
    embedding_service.sync_stale_communities = AsyncMock(
        side_effect=RuntimeError("embedding failed")
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
        patch("src.core.graph.application.communities.leiden.CommunityDetector") as detector,
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
        with pytest.raises(CommunityPhaseError, match="embedding failed") as error:
            await _process_communities_async("tenant-1", resume_from="embedding")

    assert error.value.resume_from == "embedding"
    detector.assert_not_called()
    summarizer.summarize_all_stale.assert_not_awaited()
    embedding_service.sync_stale_communities.assert_awaited_once()


@pytest.mark.asyncio
async def test_embedding_resume_keeps_checkpoint_when_setup_fails():
    settings = MagicMock()
    settings.db.database_url = "postgresql://test"
    settings.db.redis_url = "redis://test"
    platform = MagicMock()
    platform.neo4j_client.close = AsyncMock()
    tuning_service = MagicMock()
    tuning_service.get_effective_tenant_config = AsyncMock(side_effect=RuntimeError("setup failed"))

    with (
        patch("src.amber_platform.composition_root.platform", platform),
        patch("src.amber_platform.composition_root.build_vector_store_factory"),
        patch("src.api.config.settings", settings),
        patch("src.shared.kernel.runtime.configure_settings"),
        patch("src.core.database.session.configure_database"),
        patch(
            "src.core.admin_ops.application.tuning_service.TuningService",
            return_value=tuning_service,
        ),
        patch("src.core.database.session.get_session_maker"),
    ):
        with pytest.raises(CommunityPhaseError, match="setup failed") as error:
            await _process_communities_async("tenant-1", resume_from="embedding")

    assert error.value.resume_from == "embedding"
