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
    MAX_HISTORY_QUERY_CHARS,
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
async def test_malformed_turn_is_skipped_valid_turn_survives():
    """A turn whose `answer` isn't a string (corrupted/legacy data) must not
    cost every other turn in the conversation: it is dropped on its own,
    while a well-formed turn next to it still comes through untouched."""
    summary = SimpleNamespace(
        tenant_id=TENANT,
        user_id=USER,
        metadata_={
            "history": [
                {"query": "q1", "answer": 12345},
                {"query": "q2", "answer": "good"},
            ]
        },
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, USER)
    assert result == [
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "good"},
    ]
    assert not any(m["content"] == "q1" for m in result)


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


def test_total_injected_history_is_capped_keeps_most_recent_turn():
    # Two turns, each with an over-cap query (truncated to
    # MAX_HISTORY_QUERY_CHARS + ellipsis) and a max-size answer: each turn
    # alone is 301 + 2000 = 2301 chars, so both together (4602) are just over
    # MAX_HISTORY_TOTAL_CHARS (4600) — only one turn's worth fits.
    over_cap_query = "q" * (MAX_HISTORY_QUERY_CHARS + 50)
    big_answer_old = "y" * MAX_HISTORY_ANSWER_CHARS
    big_answer_new = "z" * MAX_HISTORY_ANSWER_CHARS
    turns = [
        {"query": over_cap_query, "answer": big_answer_old},
        {"query": over_cap_query, "answer": big_answer_new},
    ]
    msgs = _history_turns_to_messages(turns, max_turns=2)
    total_chars = sum(len(m["content"]) for m in msgs)
    assert total_chars <= MAX_HISTORY_TOTAL_CHARS
    # The cap must bind on a whole-turn basis: the older turn is dropped
    # *entirely* (not just its answer, which would leave a dangling user
    # message and misalign the user/assistant sequence for the rewriter) and
    # the most recent turn — the one relevant to a follow-up — survives
    # intact, user-first.
    expected_query = "q" * MAX_HISTORY_QUERY_CHARS + "…"
    assert msgs == [
        {"role": "user", "content": expected_query},
        {"role": "assistant", "content": big_answer_new},
    ]


def test_budget_break_keeps_contiguous_recent_turns_not_the_optimal_packing():
    """Pins *contiguity* as the design choice, not budget-optimal packing.

    Three turns, oldest to newest: A (tiny — would trivially fit in whatever
    budget is left), B (large), C (large, same size as B). Processing is
    newest-first (C, then B, then A). C alone fits (2302 chars, about half
    the 4600 budget). Adding B pushes the running total past the budget
    (2302 + 2302 = 4604 > 4600), so the walk stops at B via `break` — and A
    is never even examined, even though on its own it would fit comfortably
    into the ~2298 chars still free after C.

    A `break` -> `continue` mutation would instead skip past B and pick up
    A, injecting a non-contiguous {C, A} window (turn N and N-2, skipping
    N-1) and producing 4 messages instead of 2. This test exists to fail
    under that mutation: it asserts only C's turn survives, not "the most
    that would fit."""
    turn_a_tiny = {"query": "ok", "answer": "fine, understood."}
    turn_b_large = {"query": "q" * 350, "answer": "a" * 2500}
    turn_c_large = {"query": "q" * 350, "answer": "a" * 2500}
    turns = [turn_a_tiny, turn_b_large, turn_c_large]

    msgs = _history_turns_to_messages(turns, max_turns=3)

    expected_query = "q" * MAX_HISTORY_QUERY_CHARS + "…"
    expected_answer = "a" * MAX_HISTORY_ANSWER_CHARS + "…"
    assert msgs == [
        {"role": "user", "content": expected_query},
        {"role": "assistant", "content": expected_answer},
    ]


def test_p95_case_keeps_both_turns():
    """Pins the typical (not pathological) case the total cap must handle:
    two answers at the p95 observed size (2622 chars, over
    MAX_HISTORY_ANSWER_CHARS so both get capped-plus-ellipsis) and two
    realistic ~150-char queries. Both turns must survive — this used to
    collapse to 1 turn before the query got its own, smaller cap, because a
    single shared 2000-char budget let two capped answers alone
    (2 * 2001 = 4002) leave only ~198 chars for both queries combined."""
    p95_answer = "a" * 2622
    realistic_query = "q" * 150
    turns = [
        {"query": realistic_query, "answer": p95_answer},
        {"query": realistic_query, "answer": p95_answer},
    ]
    msgs = _history_turns_to_messages(turns, max_turns=2)
    assert len(msgs) == 4
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == realistic_query
    assert msgs[2]["content"] == realistic_query


def test_query_over_cap_is_truncated_separately_from_answer():
    long_query = "q" * (MAX_HISTORY_QUERY_CHARS + 100)
    turns = [{"query": long_query, "answer": "short answer"}]
    msgs = _history_turns_to_messages(turns)
    user_msg = next(m for m in msgs if m["role"] == "user")
    assert len(user_msg["content"]) <= MAX_HISTORY_QUERY_CHARS + 1  # +1 for the ellipsis mark
    assert user_msg["content"] != long_query


def test_max_turns_zero_returns_no_turns():
    """`(turns or [])[-0:]` is `[0:]` — every turn, not none. max_turns=0 must
    mean "keep zero turns", not be silently equivalent to no limit at all."""
    turns = [{"query": "q1", "answer": "a1"}, {"query": "q2", "answer": "a2"}]
    assert _history_turns_to_messages(turns, max_turns=0) == []


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

    load_history_calls: list = []

    async def _spy_load_conversation_history(*args, **kwargs):
        # Record instead of raising: an exception here would be swallowed by
        # `_query_stream_impl`'s own `except Exception` fallback, and the
        # stream would just fall through to "no chunks" — which happens to
        # also make `retrieve_kwargs` stay `{}`, so `.get("history") is None`
        # would pass for the wrong reason (retrieve() never even ran).
        load_history_calls.append((args, kwargs))
        return []

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

    assert load_history_calls == [], "_load_conversation_history must not be called when the flag is off"
    # retrieve() must actually have run (proves the assertion below isn't
    # vacuously true because the stream errored out before reaching it).
    assert "history" in retrieve_kwargs
    assert retrieve_kwargs.get("history") is None


@pytest.mark.asyncio
async def test_flag_on_injects_history_into_retrieval(monkeypatch):
    """The gate's other half: with the flag ON, a real, well-formed 2-turn
    conversation must reach retrieve() as a populated, correctly-mapped
    `history` list — not just "not None". Patches the exact object the code
    reads (`src.api.config.settings`, not `get_settings()`/
    `configure_settings()`): the gate at query.py does
    `from src.api.config import settings as _history_settings`, so patching
    a different settings instance would be a silent no-op here."""
    from src.api.config import settings as api_settings

    monkeypatch.setattr(
        api_settings, "enable_multiturn_history_reinjection", True, raising=False
    )

    summary = SimpleNamespace(
        tenant_id=TENANT,
        user_id=USER,
        metadata_={
            "history": [
                {"query": "cosa e UMR", "answer": "User Mail Replica"},
                {"query": "e le limitazioni?", "answer": "Le limitazioni sono descritte qui"},
            ]
        },
    )

    class _SessionWithSummary:
        async def get(self, *_a, **_kw):
            return summary

        def add(self, _obj):
            pass

        async def commit(self):
            pass

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
        http_request=http_request, request=request, session=_SessionWithSummary()
    )

    async for _chunk in response.body_iterator:
        pass

    assert "history" in retrieve_kwargs
    assert retrieve_kwargs["history"] == [
        {"role": "user", "content": "cosa e UMR"},
        {"role": "assistant", "content": "User Mail Replica"},
        {"role": "user", "content": "e le limitazioni?"},
        {"role": "assistant", "content": "Le limitazioni sono descritte qui"},
    ]
