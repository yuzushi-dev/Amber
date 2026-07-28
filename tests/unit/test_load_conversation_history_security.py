"""
Unit tests for the security-relevant parts of `_load_conversation_history`
(src/api/routes/query.py) and the `enable_multiturn_history_reinjection`
feature-flag gate around it.

`_load_conversation_history` had zero test coverage before this PR. These
tests lock in: a missing conversation, a foreign tenant's conversation, a
foreign user's conversation, and a persisted `metadata_` blob with no
`history` key must all resolve to `[]` — never leak another caller's turns.
A malformed turn (non-string `answer`) is also covered: today that fails
open and discards the *whole* conversation's history for this call, not just
the bad turn — documented behaviour, not a crash.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.api.routes.query import (
    MAX_HISTORY_ANSWER_CHARS,
    MAX_HISTORY_TOTAL_CHARS,
    _history_turns_to_messages,
    _load_conversation_history,
    _query_stream_impl,
)
from src.api.schemas.query import QueryOptions, QueryRequest
from src.core.generation.domain.memory_models import ConversationSummary

TENANT = "tenant-1"
USER = "user-1"


class _FakeSession:
    """Minimal stand-in for the injected AsyncSession: `_load_conversation_history`
    only ever calls `.get()` on it."""

    def __init__(self, get_result=None):
        self._get_result = get_result
        self.get_calls: list[tuple] = []

    async def get(self, model, pk):
        self.get_calls.append((model, pk))
        return self._get_result


# =============================================================================
# _load_conversation_history — ownership / existence guards
# =============================================================================


@pytest.mark.asyncio
async def test_no_conversation_id_returns_empty_without_touching_session():
    session = _FakeSession(get_result=None)
    result = await _load_conversation_history(session, None, TENANT, USER)
    assert result == []
    assert session.get_calls == []


@pytest.mark.asyncio
async def test_unknown_conversation_returns_empty():
    session = _FakeSession(get_result=None)
    result = await _load_conversation_history(session, "missing-conv", TENANT, USER)
    assert result == []


@pytest.mark.asyncio
async def test_other_tenant_conversation_is_not_leaked():
    summary = SimpleNamespace(
        tenant_id="someone-elses-tenant",
        user_id=USER,
        metadata_={"history": [{"query": "q", "answer": "a"}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, USER)
    assert result == []


@pytest.mark.asyncio
async def test_other_user_conversation_is_not_leaked():
    summary = SimpleNamespace(
        tenant_id=TENANT,
        user_id="someone-else",
        metadata_={"history": [{"query": "q", "answer": "a"}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, USER)
    assert result == []


@pytest.mark.asyncio
async def test_metadata_without_history_key_returns_empty():
    summary = SimpleNamespace(tenant_id=TENANT, user_id=USER, metadata_={})
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, USER)
    assert result == []


@pytest.mark.asyncio
async def test_malformed_turn_fails_open_to_empty_history():
    """A turn whose `answer` isn't a string (corrupted/legacy data) must not
    propagate an exception out to the caller; today it fails open by
    discarding the whole conversation's history for this call."""
    summary = SimpleNamespace(
        tenant_id=TENANT,
        user_id=USER,
        metadata_={"history": [{"query": "valid query", "answer": 12345}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, USER)
    assert result == []


@pytest.mark.asyncio
async def test_valid_conversation_reuses_injected_session():
    """Happy path: proves the function reads through the *injected* session
    (no `_get_async_session_maker()()` call, nothing to patch/await besides
    the fake) and that the ownership match returns the mapped messages."""
    summary = SimpleNamespace(
        tenant_id=TENANT,
        user_id=USER,
        metadata_={"history": [{"query": "cosa e UMR", "answer": "User Mail Replica"}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, USER)
    assert result == [
        {"role": "user", "content": "cosa e UMR"},
        {"role": "assistant", "content": "User Mail Replica"},
    ]
    # Exactly one .get() call, on the same session the caller already has —
    # this is the identity-map hit the sticky check's earlier .get() enables,
    # not a second round-trip to Postgres.
    assert session.get_calls == [(ConversationSummary, "conv-1")]


# =============================================================================
# _history_turns_to_messages — length caps
# =============================================================================


def test_answer_over_cap_is_truncated():
    long_answer = "x" * (MAX_HISTORY_ANSWER_CHARS + 500)
    turns = [{"query": "q", "answer": long_answer}]
    msgs = _history_turns_to_messages(turns)
    assistant_msg = next(m for m in msgs if m["role"] == "assistant")
    assert len(assistant_msg["content"]) <= MAX_HISTORY_ANSWER_CHARS + 1  # +1 for the ellipsis mark
    assert assistant_msg["content"] != long_answer


def test_total_injected_history_is_capped():
    # Two turns, each with a max-size answer and a long-ish query: unbounded
    # this would inject ~2 * (150 + 2000) = 4300 chars, over the total cap.
    big_answer = "y" * MAX_HISTORY_ANSWER_CHARS
    long_query = "q" * 150
    turns = [
        {"query": long_query, "answer": big_answer},
        {"query": long_query, "answer": big_answer},
    ]
    msgs = _history_turns_to_messages(turns, max_turns=2)
    total_chars = sum(len(m["content"]) for m in msgs)
    assert total_chars <= MAX_HISTORY_TOTAL_CHARS
    # The cap must actually bind (something got dropped), not just happen to
    # fit — otherwise this test would pass even if the cap were a no-op.
    assert len(msgs) < 4


# =============================================================================
# enable_multiturn_history_reinjection — flag gate is a full no-op when off
# =============================================================================


@pytest.mark.asyncio
async def test_flag_off_never_loads_conversation_history(monkeypatch):
    """With the flag off (the default), the reinjection code path must be a
    complete no-op: `_load_conversation_history` is never even called, so
    there's no extra DB read, and `history=None` reaches retrieval."""
    from src.api.config import settings as api_settings
    from src.shared.kernel.runtime import configure_settings

    configure_settings(api_settings)
    monkeypatch.setattr(
        api_settings, "enable_multiturn_history_reinjection", False, raising=False
    )

    async def _spy_load_conversation_history(*_args, **_kwargs):
        raise AssertionError(
            "_load_conversation_history must not be called when the flag is off"
        )

    monkeypatch.setattr(
        "src.api.routes.query._load_conversation_history", _spy_load_conversation_history
    )
    monkeypatch.setattr(
        "src.core.retrieval.application.query.structured_query.structured_executor.try_execute",
        AsyncMock(return_value=None),
    )

    retrieve_kwargs: dict = {}

    async def fake_retrieve(**kwargs):
        retrieve_kwargs.update(kwargs)
        return SimpleNamespace(chunks=[{"score": 0.9}], cache_hit=False)

    async def fake_generate_stream(**_kw):
        yield {"event": "token", "data": "Hello"}
        yield {"event": "sources", "data": []}
        yield {"event": "done", "data": {"model": "test-model", "provider": "test-provider"}}

    generation_service = SimpleNamespace(
        generate_stream=fake_generate_stream,
        _normalize_citations=lambda text: text,
    )
    retrieval_service = SimpleNamespace(retrieve=fake_retrieve)

    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_retrieval_service",
        lambda _session: retrieval_service,
        raising=False,
    )
    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_generation_service",
        lambda _session: generation_service,
        raising=False,
    )

    class _SessionStub:
        async def get(self, *_a, **_kw):
            return None

        def add(self, _obj):
            pass

        async def commit(self):
            pass

    request = QueryRequest(
        query="continue our chat",
        options=QueryOptions(model="test-model"),
        conversation_id="conv-existing",
    )
    http_request = SimpleNamespace(
        method="POST",
        state=SimpleNamespace(tenant_id=TENANT, query_scopes=None, is_super_admin=False),
        headers={"X-User-ID": USER},
    )

    response = await _query_stream_impl(
        http_request=http_request, request=request, session=_SessionStub()
    )

    async for _chunk in response.body_iterator:
        pass

    assert retrieve_kwargs.get("history") is None
