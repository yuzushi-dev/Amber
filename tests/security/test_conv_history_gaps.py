"""
Security tests for conversation history gaps.

Covers:
- admin/chat_history.py requires super_admin
- query.py agent mode writes resolved user_id (not "user")
- query.py threading update checks tenant ownership
- query.py RAG update checks tenant+user ownership
"""

import inspect
from unittest.mock import MagicMock

import pytest

# ── Helper factories ─────────────────────────────────────────────────────────


def _make_request(tenant_id="tenant-a", api_key_name="key-001", user_id_header=None):
    req = MagicMock()
    req.method = "POST"
    req.state.tenant_id = tenant_id
    req.state.api_key_name = api_key_name
    req.state.is_super_admin = False
    req.state.tenant_role = None
    headers = {}
    if user_id_header:
        headers["X-User-ID"] = user_id_header
    req.headers = headers
    return req


def _non_admin_request():
    req = _make_request()
    req.state.is_super_admin = False
    req.state.permissions = ["active_user"]
    return req


# ── Fix 1: admin/chat_history.py — router-level guard ───────────────────────


@pytest.mark.asyncio
async def test_chat_history_admin_rejects_non_admin():
    """
    admin/chat_history.py must reject non-super-admin callers with 403.
    Any key that is not super_admin must be blocked.
    """
    from fastapi import HTTPException

    from src.api.deps import verify_super_admin

    req = _non_admin_request()
    with pytest.raises(HTTPException) as exc_info:
        await verify_super_admin(req)
    assert exc_info.value.status_code == 403


def test_chat_history_router_has_super_admin_dependency():
    """
    admin/chat_history.py router must declare verify_super_admin as a dependency
    so no individual handler can be reached without super_admin.
    """
    import src.api.routes.admin.chat_history as ch_module
    from src.api.deps import verify_super_admin

    router = ch_module.router
    dep_fns = [d.dependency for d in router.dependencies]
    assert verify_super_admin in dep_fns, (
        "admin/chat_history router is missing verify_super_admin dependency. "
        "Any authenticated key can list or delete conversations across all tenants."
    )


# ── Fix 2: agent mode writes resolved user_id ────────────────────────────────


def test_query_py_no_hardcoded_user_sentinel_in_agent_insert():
    """
    query.py must not contain the literal user_id=\"user\" string used for
    agent-mode conversation inserts.  The resolved principal must be used instead.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert 'user_id="user",  # Default user' not in source, (
        "query.py still contains user_id='user' for agent conversation inserts. "
        "All agent conversations will be stored under a shared 'user' identity."
    )


def test_query_py_agent_insert_uses_stream_user_id():
    """
    query.py agent-mode ConversationSummary insert must reference stream_user_id,
    the caller-resolved principal set earlier in generate_stream().
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert "user_id=stream_user_id" in source, (
        "query.py agent insert does not reference stream_user_id. "
        "Agent conversations will be attributed to wrong identity."
    )


# ── Fix 3: stream_user_id is resolved before sticky/agent blocks ─────────────


def test_query_py_stream_user_id_resolved_early():
    """
    generate_stream() must resolve stream_user_id before the sticky mode check
    so it is available for both the sticky check and the agent/RAG persist blocks.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    stream_pos = source.find("stream_user_id = _get_user_id(")
    sticky_pos = source.find("# STICKY MODE CHECK")
    assert stream_pos != -1, "stream_user_id not resolved in generate_stream"
    assert stream_pos < sticky_pos, (
        "stream_user_id must be resolved BEFORE the sticky mode check block."
    )


# ── Fix 4: tenant ownership checked before threading update ──────────────────


def test_query_py_sticky_check_verifies_tenant():
    """
    The sticky mode check must compare existing_conv.tenant_id against the
    caller's tenant_id before trusting conversation mode metadata.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert "existing_conv.tenant_id != tenant_id" in source, (
        "Sticky mode check does not verify tenant ownership. "
        "A caller can auto-switch into agent mode using a foreign tenant's conversation ID."
    )


# ── Fix 4b: api_key_id ownership + legacy adoption on persistence (#72) ──────


class _FakeRlsSession:
    """Minimal AsyncSession double for `_persist_rag_conversation` /
    `_persist_agent_conversation`: only `.get()`/`.add()`/`.commit()`/
    `.rollback()`/`.execute()` are exercised by `request_rls_session()`."""

    def __init__(self, get_result=None):
        self._get_result = get_result
        self.added: list = []

    async def get(self, _model, _pk):
        return self._get_result

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, *_a, **_kw):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_exc):
        return False


class _FakeSessionMaker:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return _FakeSessionContext(self.session)


def _fake_rls_context():
    from src.api.deps import RequestRlsContext

    return RequestRlsContext(
        tenant_id="tenant-a",
        is_super_admin=False,
        group_ids=(),
        tenant_role="user",
        groups_enforced=False,
    )


@pytest.mark.asyncio
async def test_rag_persist_rejects_foreign_api_key(monkeypatch, caplog):
    """A caller authenticated with a different api_key_id than the one that
    created the conversation must not be able to append to its history —
    the vulnerability this replaces let any same-tenant caller who knew a
    conversation_id append to another user's history via a spoofable
    user_id check."""
    from src.api.routes.query import _persist_rag_conversation
    from src.core.generation.domain.memory_models import ConversationSummary

    existing = ConversationSummary(
        id="conv-1", tenant_id="tenant-a", api_key_id="key-owner", user_id="owner-user-id",
        title="t", summary="s", metadata_={"history": []},
    )
    session = _FakeRlsSession(get_result=existing)
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker", lambda: _FakeSessionMaker(session)
    )

    with caplog.at_level("WARNING"):
        await _persist_rag_conversation(
            rls_context=_fake_rls_context(),
            conversation_id="conv-1",
            tenant_id="tenant-a",
            stream_user_id="attacker-user-id",
            api_key_id="key-attacker",
            query="q",
            answer="a",
            sources=[],
            quality=None,
        )

    assert "Skipping foreign RAG conversation persistence" in caplog.text, (
        "Rejection must go through the explicit foreign-key guard, not an "
        "unrelated exception the outer try/except happens to swallow."
    )
    assert session.added == [], "Foreign api_key_id must not be able to append to the conversation"
    assert existing.metadata_["history"] == []


@pytest.mark.asyncio
async def test_rag_persist_allows_matching_api_key(monkeypatch):
    from src.api.routes.query import _persist_rag_conversation
    from src.core.generation.domain.memory_models import ConversationSummary

    existing = ConversationSummary(
        id="conv-1", tenant_id="tenant-a", api_key_id="key-owner", user_id="owner-user-id",
        title="t", summary="s", metadata_={"history": []},
    )
    session = _FakeRlsSession(get_result=existing)
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker", lambda: _FakeSessionMaker(session)
    )

    await _persist_rag_conversation(
        rls_context=_fake_rls_context(),
        conversation_id="conv-1",
        tenant_id="tenant-a",
        stream_user_id="owner-user-id",
        api_key_id="key-owner",
        query="q2",
        answer="a2",
        sources=[],
        quality=None,
    )

    assert len(existing.metadata_["history"]) == 1
    assert session.added == [existing]


@pytest.mark.asyncio
async def test_rag_persist_adopts_legacy_conversation_with_no_api_key_id(monkeypatch):
    """A conversation written before the api_key_id column existed (NULL)
    must be adopted by the first authenticated same-tenant write, not
    orphaned into a silent no-op forever — no worse than the pre-fix
    behaviour (any same-tenant caller could already update it with zero
    ownership check), but durable and provably owned afterward."""

    from src.api.routes.query import _persist_rag_conversation
    from src.core.generation.domain.memory_models import ConversationSummary

    existing = ConversationSummary(
        id="conv-legacy", tenant_id="tenant-a", api_key_id=None, user_id="first-writer",
        title="t", summary="s", metadata_={"history": []},
    )
    session = _FakeRlsSession(get_result=existing)
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker", lambda: _FakeSessionMaker(session)
    )

    await _persist_rag_conversation(
        rls_context=_fake_rls_context(),
        conversation_id="conv-legacy",
        tenant_id="tenant-a",
        stream_user_id="first-writer",
        api_key_id="key-first-writer",
        query="q",
        answer="a",
        sources=[],
        quality=None,
    )

    assert existing.api_key_id == "key-first-writer"
    assert len(existing.metadata_["history"]) == 1


@pytest.mark.asyncio
async def test_agent_persist_rejects_foreign_api_key(monkeypatch, caplog):
    from src.api.routes.query import _persist_agent_conversation
    from src.core.generation.domain.memory_models import ConversationSummary

    existing = ConversationSummary(
        id="conv-1", tenant_id="tenant-a", api_key_id="key-owner", user_id="owner-user-id",
        title="t", summary="s", metadata_={"history": []},
    )
    session = _FakeRlsSession(get_result=existing)
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker", lambda: _FakeSessionMaker(session)
    )

    with caplog.at_level("WARNING"):
        result = await _persist_agent_conversation(
            rls_context=_fake_rls_context(),
            conversation_id="conv-1",
            tenant_id="tenant-a",
            user_id="attacker-user-id",
            api_key_id="key-attacker",
            query="q",
            answer="a",
            sources=[],
            tools_used=[],
        )

    assert "Skipping foreign agent conversation persistence" in caplog.text
    assert result is False
    assert session.added == []


def test_query_py_agent_update_verifies_tenant():
    """
    The agent-mode ConversationSummary update block must check tenant_id
    before appending to an existing conversation.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert "_resolve_owned_summary(" in source and "existing.tenant_id != tenant_id" in source, (
        "Agent update block does not verify tenant ownership via _resolve_owned_summary."
    )
