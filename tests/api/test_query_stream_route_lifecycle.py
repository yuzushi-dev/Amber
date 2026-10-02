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
    def __init__(self):
        self.prepare_kwargs = None

    async def prepare_stream(self, **kwargs):
        self.prepare_kwargs = kwargs
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
    retrieval_calls = []
    recorded_metrics = []
    generation = _Generation()

    async def structured_precheck(**_kwargs):
        return None

    async def retrieve(**kwargs):
        retrieval_calls.append(kwargs)
        return SimpleNamespace(
            chunks=[{"chunk_id": "chunk-1", "score": 1.0}],
            cache_hit=False,
            search_mode="basic",
            reranking_ms=0.0,
        )

    async def no_graph_write(**_kwargs):
        return None

    class _MetricsCollector:
        def __init__(self, **_kwargs):
            pass

        async def record(self, _metrics):
            recorded_metrics.append(_metrics)
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
        lambda _session: generation,
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
    recorded_usage = []

    async def record_usage(_self, **kwargs):
        recorded_usage.append(kwargs)

    monkeypatch.setattr(
        "src.core.admin_ops.application.usage_tracker.UsageTracker.record_usage", record_usage
    )

    app = FastAPI()

    @app.middleware("http")
    async def authenticated_request(request: Request, call_next):
        request.state.tenant_id = "tenant-a"
        request.state.api_key_id = "key-a"
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
            json={
                "query": "Explain the alerting setup",
                "filters": {
                    "document_ids": [],
                    "edition": "commercial",
                    "audience": "admin",
                    "source_family": "zendesk_kb",
                },
                "history": [{"query": "What is the alert?", "answer": "A signal."}],
                "options": {"model": "test", "include_trace": True, "search_mode": "drift"},
            },
        )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert len(sessions.sessions) == 2
    assert retrieval_calls[0]["document_ids"] == []
    assert retrieval_calls[0]["filters"] == {
        "edition": "commercial",
        "audience": "admin",
        "source_family": "zendesk_kb",
    }
    expected_history = [
        {"role": "user", "content": "What is the alert?"},
        {"role": "assistant", "content": "A signal."},
    ]
    assert retrieval_calls[0]["history"] == expected_history
    assert generation.prepare_kwargs["conversation_history"] == expected_history
    assert generation.prepare_kwargs["options"]["include_trace"] is True
    assert recorded_metrics[0].search_mode == "basic"
    # streamed answers are written to usage_logs (generate_stream itself does not)
    assert len(recorded_usage) == 1
    assert recorded_usage[0]["operation"] == "generation"
    assert recorded_usage[0]["provider"] == "test"
    assert recorded_usage[0]["usage"].output_tokens > 0
    assert recorded_usage[0]["metadata"]["stream"] is True
