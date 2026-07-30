"""Hermetic lifecycle tests for query SSE database phases.

These tests exercise the route's real request-RLS session factory.  Service
doubles replace only provider/retrieval work, then block at the provider
boundary so a checked-out SQLAlchemy session would be observable.
"""

import asyncio
from types import SimpleNamespace

import pytest

from src.api.deps import get_request_rls_context
from src.api.routes.query import _query_stream_impl, _ScopedAgentRetrievalService
from src.api.schemas.query import QueryOptions, QueryRequest

RLS_GUCS = [
    "app.current_tenant",
    "app.is_super_admin",
    "app.current_groups",
    "app.tenant_role",
    "app.groups_enforced",
]


class _TrackingSession:
    def __init__(self, factory: "_TrackingSessionMaker", number: int):
        self.factory = factory
        self.number = number
        self.gucs: list[str] = []
        self.guc_values: list[object] = []
        self.get_calls: list[tuple[object, str]] = []
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "set_config" in sql:
            start = sql.index("app.")
            self.gucs.append(sql[start:].split("'", 1)[0])
            self.guc_values.append(next(iter((params or {}).values())))

    async def get(self, model, identifier):
        self.get_calls.append((model, identifier))
        # A session that can see a foreign summary must not add or update it.
        if self.number == 2:
            return SimpleNamespace(
                id=identifier,
                tenant_id="foreign-tenant",
                user_id="foreign-user",
                metadata_={"history": []},
            )
        return None

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _TrackingSessionContext:
    def __init__(self, factory: "_TrackingSessionMaker"):
        self.factory = factory
        self.session = _TrackingSession(factory, len(factory.sessions) + 1)

    async def __aenter__(self):
        self.factory.active += 1
        self.factory.sessions.append(self.session)
        return self.session

    async def __aexit__(self, *_exc):
        self.factory.active -= 1
        return False


class _TrackingSessionMaker:
    def __init__(self):
        self.active = 0
        self.sessions: list[_TrackingSession] = []

    def __call__(self):
        return _TrackingSessionContext(self)


class _BlockingGenerationService:
    def __init__(self, factory: _TrackingSessionMaker):
        self.factory = factory
        self.provider_started = asyncio.Event()
        self.release_provider = asyncio.Event()
        self.provider_active_counts: list[int] = []

    async def generate_stream(self, **_kwargs):
        """Compatibility path used by the old implementation during the RED run."""
        self.provider_started.set()
        self.provider_active_counts.append(self.factory.active)
        await self.release_provider.wait()
        yield {"event": "token", "data": "Hello"}
        yield {"event": "sources", "data": []}
        yield {"event": "done", "data": {"model": "test", "provider": "test"}}

    async def prepare_stream(self, **_kwargs):
        return SimpleNamespace(prelude_events=())

    async def stream_prepared(self, _prepared):
        self.provider_started.set()
        self.provider_active_counts.append(self.factory.active)
        await self.release_provider.wait()
        yield {"event": "token", "data": "Hello"}
        yield {"event": "sources", "data": []}
        yield {"event": "done", "data": {"model": "test", "provider": "test"}}

    @staticmethod
    def _normalize_citations(text: str) -> str:
        return text


class _BlockingAgent:
    def __init__(self, generation: _BlockingGenerationService, **_kwargs):
        self.generation = generation

    async def run(self, **_kwargs):
        self.generation.provider_started.set()
        self.generation.provider_active_counts.append(self.generation.factory.active)
        await self.generation.release_provider.wait()
        return SimpleNamespace(answer="Agent answer", sources=[], trace=[])


def _http_request():
    return SimpleNamespace(
        method="POST",
        state=SimpleNamespace(
            tenant_id="tenant-a",
            permissions=["super_admin"],
            group_ids=["group-a", "group-b"],
            tenant_role="admin",
            groups_enforced=True,
            query_scopes=None,
            is_super_admin=True,
        ),
        headers={"X-User-ID": "user-a"},
    )


async def _drain(response):
    async for _chunk in response.body_iterator:
        pass


def _patch_common(monkeypatch, factory, generation):
    async def structured_precheck(**_kwargs):
        return None

    async def retrieve(**_kwargs):
        return SimpleNamespace(chunks=[{"chunk_id": "chunk-1", "score": 1.0}], cache_hit=False)

    monkeypatch.setattr("src.api.deps._get_async_session_maker", lambda: factory)
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


def _assert_rls_phases(factory: _TrackingSessionMaker):
    assert len(factory.sessions) == 2
    assert factory.active == 0
    assert [session.gucs for session in factory.sessions] == [RLS_GUCS, RLS_GUCS]
    assert [session.guc_values for session in factory.sessions] == [
        ["tenant-a", "true", "group-a,group-b", "admin", "true"],
        ["tenant-a", "true", "group-a,group-b", "admin", "true"],
    ]
    assert all(session.commits == 1 for session in factory.sessions)


@pytest.mark.asyncio
async def test_rag_stream_closes_pre_phase_before_provider_and_reloads_post_phase(monkeypatch):
    factory = _TrackingSessionMaker()
    generation = _BlockingGenerationService(factory)
    _patch_common(monkeypatch, factory, generation)

    request = QueryRequest(
        query="Explain the alerting setup",
        options=QueryOptions(model="test"),
        conversation_id="conversation-1",
    )
    response = await _query_stream_impl(http_request=_http_request(), request=request)
    drain_task = asyncio.create_task(_drain(response))
    try:
        await asyncio.wait_for(generation.provider_started.wait(), timeout=1)
        assert generation.provider_active_counts == [0]
    finally:
        generation.release_provider.set()
        await asyncio.wait_for(drain_task, timeout=1)

    _assert_rls_phases(factory)
    assert [identifier for _model, identifier in factory.sessions[1].get_calls] == [
        "conversation-1"
    ]
    assert factory.sessions[1].added == []


@pytest.mark.asyncio
async def test_agent_retrieval_tool_opens_its_own_short_rls_phase(monkeypatch):
    factory = _TrackingSessionMaker()
    monkeypatch.setattr("src.api.deps._get_async_session_maker", lambda: factory)

    async def retrieve(**_kwargs):
        assert factory.active == 1
        return SimpleNamespace(chunks=[])

    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_retrieval_service",
        lambda _session: SimpleNamespace(retrieve=retrieve),
    )

    # The context is produced by the real request-state snapshotter in stream
    # execution; the values here mirror the authenticated request.
    service = _ScopedAgentRetrievalService(get_request_rls_context(_http_request()))
    result = await service.retrieve(query="find alerts", tenant_id="tenant-a")

    assert result.chunks == []
    assert factory.active == 0
    assert [session.gucs for session in factory.sessions] == [RLS_GUCS]
    assert factory.sessions[0].guc_values == [
        "tenant-a",
        "true",
        "group-a,group-b",
        "admin",
        "true",
    ]


@pytest.mark.asyncio
async def test_agent_stream_closes_pre_phase_before_provider_and_reloads_post_phase(monkeypatch):
    factory = _TrackingSessionMaker()
    generation = _BlockingGenerationService(factory)
    _patch_common(monkeypatch, factory, generation)

    monkeypatch.setattr("src.api.config.settings.enable_agent_mode", True, raising=False)
    monkeypatch.setattr(
        "src.core.generation.application.agent.orchestrator.AgentOrchestrator",
        lambda **kwargs: _BlockingAgent(generation, **kwargs),
    )
    monkeypatch.setattr(
        "src.core.generation.domain.memory_models.ConversationSummary",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    request = QueryRequest(
        query="Inspect the workspace",
        options=QueryOptions(agent_mode=True),
        conversation_id="conversation-1",
    )
    response = await _query_stream_impl(http_request=_http_request(), request=request)
    drain_task = asyncio.create_task(_drain(response))
    try:
        await asyncio.wait_for(generation.provider_started.wait(), timeout=1)
        assert generation.provider_active_counts == [0]
    finally:
        generation.release_provider.set()
        await asyncio.wait_for(drain_task, timeout=1)

    _assert_rls_phases(factory)
    assert [identifier for _model, identifier in factory.sessions[1].get_calls] == [
        "conversation-1"
    ]
    assert factory.sessions[1].added == []
