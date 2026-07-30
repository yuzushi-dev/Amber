"""ASGI regression coverage for the query SSE route's DB lifetime."""

from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.routes import query


class _Session:
    def __init__(self, factory: "_SessionMaker"):
        self.factory = factory

    async def execute(self, *_args, **_kwargs):
        return None

    async def get(self, *_args, **_kwargs):
        return None

    def add(self, _value):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _SessionContext:
    def __init__(self, factory: "_SessionMaker"):
        self.factory = factory

    async def __aenter__(self):
        self.factory.sessions.append(_Session(self.factory))
        return self.factory.sessions[-1]

    async def __aexit__(self, *_exc):
        return False


class _SessionMaker:
    def __init__(self):
        self.sessions: list[_Session] = []

    def __call__(self):
        return _SessionContext(self)


class _Generation:
    async def prepare_stream(self, **_kwargs):
        return SimpleNamespace(prelude_events=())

    async def stream_prepared(self, _prepared):
        yield {"event": "token", "data": "Grounded answer"}
        yield {"event": "done", "data": {"model": "test", "provider": "test"}}

    @staticmethod
    def _normalize_citations(text: str) -> str:
        return text


def test_query_stream_route_has_no_request_scoped_database_dependency(monkeypatch):
    """A reintroduced ``Depends(get_db_session)`` would create a third session."""
    sessions = _SessionMaker()

    async def structured_precheck(**_kwargs):
        return None

    async def retrieve(**_kwargs):
        return SimpleNamespace(chunks=[{"chunk_id": "chunk-1", "score": 1.0}], cache_hit=False)

    async def no_graph_write(**_kwargs):
        return None

    class _MetricsCollector:
        def __init__(self, **_kwargs):
            pass

        async def record(self, _metrics):
            return None

        async def close(self):
            return None

    monkeypatch.setattr("src.api.deps._get_async_session_maker", lambda: sessions)
    monkeypatch.setattr(
        "src.core.retrieval.application.query.structured_query.structured_executor.try_execute",
        structured_precheck,
    )
    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_retrieval_service",
        lambda _session: SimpleNamespace(retrieve=retrieve),
    )
    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_generation_service",
        lambda _session: _Generation(),
    )
    monkeypatch.setattr(
        "src.core.generation.domain.memory_models.ConversationSummary",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "src.core.graph.application.context_writer.context_graph_writer.log_turn", no_graph_write
    )
    monkeypatch.setattr(
        "src.core.admin_ops.application.metrics.collector.MetricsCollector", _MetricsCollector
    )

    app = FastAPI()

    @app.middleware("http")
    async def authenticated_request(request: Request, call_next):
        request.state.tenant_id = "tenant-a"
        request.state.permissions = []
        request.state.group_ids = []
        request.state.tenant_role = "user"
        request.state.groups_enforced = False
        request.state.query_scopes = None
        request.state.is_super_admin = False
        return await call_next(request)

    app.include_router(query.router)

    with TestClient(app) as client:
        response = client.post(
            "/query/stream",
            headers={"X-User-ID": "user-a"},
            json={"query": "Explain the alerting setup", "options": {"model": "test"}},
        )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert len(sessions.sessions) == 2
