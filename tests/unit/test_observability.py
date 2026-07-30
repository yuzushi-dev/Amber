import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.asyncio as aioredis

from src.amber_platform.composition_root import platform
from src.api.routes.admin import observability

EXPECTED_STATUS_KEYS = {"database", "redis", "neo4j", "milvus"}


def _assert_exception_was_logged(caplog, marker: str) -> None:
    assert marker in caplog.text
    assert any(
        record.name == observability.__name__ and record.exc_info is not None
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_deep_health_check_redacts_redis_exception(monkeypatch, caplog):
    marker = "redis-sensitive-marker"
    redis_client = MagicMock()
    redis_client.ping = AsyncMock(side_effect=RuntimeError(marker))
    redis_client.close = AsyncMock()
    neo4j_client = MagicMock()
    neo4j_client.verify_connectivity = AsyncMock()

    monkeypatch.setattr(aioredis, "from_url", MagicMock(return_value=redis_client))
    monkeypatch.setattr(platform, "_neo4j_client", neo4j_client)
    caplog.set_level(logging.ERROR, logger=observability.__name__)

    status = await observability.deep_health_check()

    assert set(status) == EXPECTED_STATUS_KEYS
    assert status["redis"] == "error"
    assert status["neo4j"] == "ok"
    assert marker not in str(status)
    _assert_exception_was_logged(caplog, marker)


@pytest.mark.asyncio
async def test_deep_health_check_redacts_neo4j_exception(monkeypatch, caplog):
    marker = "neo4j-sensitive-marker"
    redis_client = MagicMock()
    redis_client.ping = AsyncMock()
    redis_client.close = AsyncMock()
    neo4j_client = MagicMock()
    neo4j_client.verify_connectivity = AsyncMock(side_effect=RuntimeError(marker))

    monkeypatch.setattr(aioredis, "from_url", MagicMock(return_value=redis_client))
    monkeypatch.setattr(platform, "_neo4j_client", neo4j_client)
    caplog.set_level(logging.ERROR, logger=observability.__name__)

    status = await observability.deep_health_check()

    assert set(status) == EXPECTED_STATUS_KEYS
    assert status["redis"] == "ok"
    assert status["neo4j"] == "error"
    assert marker not in str(status)
    _assert_exception_was_logged(caplog, marker)
