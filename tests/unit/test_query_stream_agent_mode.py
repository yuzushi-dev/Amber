from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from src.api.routes.query import _query_stream_impl
from src.api.schemas.query import QueryRequest
from src.shared.kernel.models.query import QueryOptions


class StubConversationSummary:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class StubSession:
    async def get(self, *_args, **_kwargs):
        return None

    def add(self, _obj):
        return None

    async def commit(self):
        return None


class StubSessionContext:
    async def __aenter__(self):
        return StubSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class StubSessionMaker:
    def __call__(self):
        return StubSessionContext()


class StubAgentOrchestrator:
    def __init__(self, **_kwargs):
        pass

    async def run(self, **_kwargs):
        return SimpleNamespace(
            answer="Agent answer",
            sources=[{"chunk_id": "chunk-1", "document_id": "doc-1", "score": 0.95}],
        )


def _build_post_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/query/stream",
        "raw_path": b"/query/stream",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    request = Request(scope)
    request.state.tenant_id = "tenant-test"
    return request


@pytest.mark.asyncio
async def test_query_stream_agent_mode_emits_done(monkeypatch):
    async def _dummy_tool(*_args, **_kwargs):
        return {"ok": True}

    def _create_retrieval_tool(_retrieval_service, _tenant_id):
        return {
            "name": "retrieve_context",
            "func": _dummy_tool,
            "schema": {"name": "retrieve_context"},
        }

    def _create_filesystem_tools(*_args, **_kwargs):
        return [
            {
                "name": "list_files",
                "func": _dummy_tool,
                "schema": {"name": "list_files"},
            }
        ]

    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_retrieval_service",
        lambda _session: MagicMock(),
    )
    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_generation_service",
        lambda _session: MagicMock(),
    )
    monkeypatch.setattr(
        "src.core.generation.application.agent.orchestrator.AgentOrchestrator",
        StubAgentOrchestrator,
    )
    monkeypatch.setattr(
        "src.core.tools.retrieval.create_retrieval_tool",
        _create_retrieval_tool,
    )
    monkeypatch.setattr(
        "src.core.tools.filesystem.create_filesystem_tools",
        _create_filesystem_tools,
    )
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker",
        lambda: StubSessionMaker(),
    )
    monkeypatch.setattr(
        "src.core.generation.domain.memory_models.ConversationSummary",
        StubConversationSummary,
    )

    request = QueryRequest(
        query="Summarize workspace",
        options=QueryOptions(agent_mode=True, agent_role="maintainer"),
    )

    response = await _query_stream_impl(
        http_request=_build_post_request(),
        request=request,
        session=MagicMock(),
    )

    payload_parts: list[str] = []
    async for chunk in response.body_iterator:
        payload_parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(payload_parts)
    assert "event: conversation_id" in payload
    assert "event: done" in payload
    assert "Agent answer" in payload
    assert "event: processing_error" not in payload
