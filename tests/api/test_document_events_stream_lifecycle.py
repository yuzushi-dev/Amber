"""ASGI lifecycle regression coverage for the document-status SSE endpoint."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.api.routes import documents


class _TrackingSession:
    def __init__(self, lifecycle: list[str]):
        self.lifecycle = lifecycle
        self.closed = False

    async def commit(self) -> None:
        self.lifecycle.append("commit")

    async def close(self) -> None:
        self.closed = True
        self.lifecycle.append("close")


class _GuardedDocument:
    """An ORM-shaped object that rejects access after its session is closed."""

    def __init__(self, session: _TrackingSession):
        self._session = session

    @property
    def status(self):
        if self._session.closed:
            raise RuntimeError("ORM object accessed after its session was closed")
        return SimpleNamespace(value="processing")


class _BlockingPubSub:
    async def subscribe(self, _channel: str) -> None:
        return None

    async def get_message(self, **_kwargs):
        await asyncio.Event().wait()

    async def unsubscribe(self, _channel: str) -> None:
        return None

    async def close(self) -> None:
        return None


class _RedisClient:
    def pubsub(self) -> _BlockingPubSub:
        return _BlockingPubSub()

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_document_event_stream_releases_db_before_first_body(monkeypatch):
    """The endpoint must snapshot ORM data before a function-scoped dependency closes."""
    lifecycle: list[str] = []
    session = _TrackingSession(lifecycle)

    async def db_dependency():
        try:
            yield session
            await session.commit()
        finally:
            await session.close()

    async def visible_document(_document_id, _request, _session):
        return SimpleNamespace(
            document=_GuardedDocument(session),
            owner_tenant_id="tenant-a",
        )

    monkeypatch.setattr(documents, "_get_visible_document_or_404", visible_document)
    monkeypatch.setattr(documents.redis, "from_url", lambda *_args, **_kwargs: _RedisClient())

    app = FastAPI()
    app.include_router(documents.router)
    app.dependency_overrides[documents.get_db_session] = db_dependency

    sent: list[dict] = []
    initial_body_sent = asyncio.Event()
    receive_queue: asyncio.Queue[dict] = asyncio.Queue()
    await receive_queue.put({"type": "http.request", "body": b"", "more_body": False})

    async def receive():
        return await receive_queue.get()

    async def send(message: dict) -> None:
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            initial_body_sent.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/documents/doc-1/events",
        "raw_path": b"/documents/doc-1/events",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(initial_body_sent.wait(), timeout=1)
        assert lifecycle == ["commit", "close"]
        assert any(b'"status": "processing"' in item.get("body", b"") for item in sent)
    finally:
        await receive_queue.put({"type": "http.disconnect"})
        await asyncio.wait_for(task, timeout=1)
