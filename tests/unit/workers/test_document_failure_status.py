"""The Celery wrapper must not hide a published document after a replacement fails."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import MaxRetriesExceededError

from src.core.state.machine import DocumentStatus
from src.workers import tasks


class _Session:
    def __init__(self, document):
        self.document = document
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _statement):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.document))


def _run(coro):
    return asyncio.run(coro)


def _fail_through_wrapper(document):
    session = _Session(document)
    sessionmaker = MagicMock(return_value=session)
    engine = MagicMock()
    engine.dispose = AsyncMock()

    with (
        patch.object(tasks, "_is_revoked", return_value=False),
        patch.object(
            tasks, "_process_document_async", new=AsyncMock(side_effect=RuntimeError("boom"))
        ),
        patch.object(tasks, "run_async", side_effect=_run),
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine),
        patch("sqlalchemy.orm.sessionmaker", return_value=sessionmaker),
        patch("src.core.database.session.configure_worker_session", new=AsyncMock()),
        patch.object(tasks, "_publish_status") as publish_status,
        patch.object(tasks, "_count_pending_docs_async", new=AsyncMock(return_value=1)),
        patch.object(
            tasks.process_document,
            "retry",
            side_effect=MaxRetriesExceededError("stop after wrapper handling"),
        ),
    ):
        with pytest.raises(MaxRetriesExceededError):
            tasks.process_document._orig_run("document-1", "tenant-1")

    return session, publish_status


def test_failed_replacement_keeps_the_published_document_ready():
    document = SimpleNamespace(
        id="document-1",
        status=DocumentStatus.READY,
        active_generation_id="generation-live",
    )

    session, publish_status = _fail_through_wrapper(document)

    assert document.status is DocumentStatus.READY
    session.commit.assert_not_awaited()
    publish_status.assert_not_called()


def test_failed_first_ingestion_marks_document_failed():
    document = SimpleNamespace(
        id="document-1",
        status=DocumentStatus.EMBEDDING,
        active_generation_id=None,
    )

    session, publish_status = _fail_through_wrapper(document)

    assert document.status is DocumentStatus.FAILED
    session.commit.assert_awaited_once()
    publish_status.assert_called_once_with(
        "document-1", DocumentStatus.FAILED.value, 100, error="boom"
    )


@pytest.mark.asyncio
async def test_pending_replacement_blocks_community_processing(monkeypatch):
    captured = {}

    class _Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def execute(self, statement, params):
            captured["sql"] = str(statement)
            captured["params"] = params
            return SimpleNamespace(scalar_one=lambda: 1)

    class _Engine:
        def connect(self):
            return _Connection()

        async def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", lambda _url: _Engine())

    assert await tasks._count_pending_docs_async("tenant-1") == 1
    assert "pending_generation_id IS NOT NULL" in captured["sql"]
    assert "processing_attempt_id IS NOT NULL" in captured["sql"]
