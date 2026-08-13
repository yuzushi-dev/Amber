"""
Unit tests for the security-relevant parts of `_load_conversation_history`
(src/api/routes/query.py) and the `enable_multiturn_history_reinjection`
feature-flag gate around it.

Ownership is gated on `api_key_id` (the authenticated caller identity set by
the auth middleware), not on `user_id`/X-User-ID — the latter is a
caller-controlled header. Before this file's fix (issue #72), gating on
`user_id` let one authenticated caller read another user's conversation
history by guessing `conversation_id` and sending an `X-User-ID` header
equal to the victim's resolved identity. These tests lock in: a missing
conversation, a foreign tenant's conversation, a foreign api_key's
conversation, a legacy conversation with no recorded api_key_id, a caller
with no resolvable api_key_id, and a persisted `metadata_` blob with no
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
API_KEY_ID = "key-abc-123"
OTHER_API_KEY_ID = "key-xyz-789"


class _FakeSession:
    """Minimal stand-in for the injected AsyncSession: `_load_conversation_history`
    only ever calls `.get()` on it."""

    def __init__(self, get_result=None):
        self._get_result = get_result
        self.get_calls: list[tuple] = []

    async def get(self, model, pk):
        self.get_calls.append((model, pk))
        return self._get_result


class _StreamSession(_FakeSession):
    """Request-RLS phase double used by route-level stream tests."""

    async def execute(self, *_args, **_kwargs):
        return None

    def add(self, _obj):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _StreamSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_exc):
        return False


class _StreamSessionMaker:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return _StreamSessionContext(self.session)


# =============================================================================
# _load_conversation_history — ownership / existence guards
# =============================================================================


@pytest.mark.asyncio
async def test_no_conversation_id_returns_empty_without_touching_session():
    session = _FakeSession(get_result=None)
    result = await _load_conversation_history(session, None, TENANT, API_KEY_ID)
    assert result == []
    assert session.get_calls == []


@pytest.mark.asyncio
async def test_no_api_key_id_returns_empty_without_touching_session():
    """A caller with no resolvable authenticated identity must be denied
    outright — never fall back to a permissive default."""
    session = _FakeSession(get_result=None)
    result = await _load_conversation_history(session, "conv-1", TENANT, None)
    assert result == []
    assert session.get_calls == []


@pytest.mark.asyncio
async def test_unknown_conversation_returns_empty():
    session = _FakeSession(get_result=None)
    result = await _load_conversation_history(session, "missing-conv", TENANT, API_KEY_ID)
    assert result == []


@pytest.mark.asyncio
async def test_other_tenant_conversation_is_not_leaked():
    summary = SimpleNamespace(
        tenant_id="someone-elses-tenant",
        api_key_id=API_KEY_ID,
        metadata_={"history": [{"query": "q", "answer": "a"}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, API_KEY_ID)
    assert result == []


@pytest.mark.asyncio
async def test_other_api_key_conversation_is_not_leaked():
    """The core #72 regression: a caller cannot read a conversation owned by
    a different authenticated key, even within the same tenant."""
    summary = SimpleNamespace(
        tenant_id=TENANT,
        api_key_id=OTHER_API_KEY_ID,
        metadata_={"history": [{"query": "q", "answer": "a"}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, API_KEY_ID)
    assert result == []


@pytest.mark.asyncio
async def test_legacy_conversation_with_no_api_key_id_is_not_leaked():
    """A conversation written before the api_key_id column existed
    (NULL) must fail closed on read — never treated as "no filter" or
    silently matched to whichever caller asks first. Legacy rows have no
    trustworthy owner and are never adopted, so their history is not
    re-injected."""
    summary = SimpleNamespace(
        tenant_id=TENANT,
        api_key_id=None,
        metadata_={"history": [{"query": "q", "answer": "a"}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, API_KEY_ID)
    assert result == []


@pytest.mark.asyncio
async def test_metadata_without_history_key_returns_empty():
    summary = SimpleNamespace(tenant_id=TENANT, api_key_id=API_KEY_ID, metadata_={})
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, API_KEY_ID)
    assert result == []


@pytest.mark.asyncio
async def test_malformed_turn_is_skipped_valid_turn_survives():
    """A turn whose `answer` isn't a string (corrupted/legacy data) must not
    cost every other turn in the conversation: it is dropped on its own,
    while a well-formed turn next to it still comes through untouched."""
    summary = SimpleNamespace(
        tenant_id=TENANT,
        api_key_id=API_KEY_ID,
        metadata_={
            "history": [
                {"query": "q1", "answer": 12345},
                {"query": "q2", "answer": "good"},
            ]
        },
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, API_KEY_ID)
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
        api_key_id=API_KEY_ID,
        metadata_={"history": [{"query": "cosa e UMR", "answer": "User Mail Replica"}]},
    )
    session = _FakeSession(get_result=summary)
    result = await _load_conversation_history(session, "conv-1", TENANT, API_KEY_ID)
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

    request = QueryRequest(
        query="continue our chat",
        options=QueryOptions(model="test-model"),
        conversation_id="conv-existing",
    )
    http_request = SimpleNamespace(
        method="POST",
        state=SimpleNamespace(
            tenant_id=TENANT, query_scopes=None, is_super_admin=False, api_key_id=API_KEY_ID
        ),
        headers={"X-User-ID": USER},
    )

    stream_session = _StreamSession()
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker", lambda: _StreamSessionMaker(stream_session)
    )
    response = await _query_stream_impl(http_request=http_request, request=request)

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
        api_key_id=API_KEY_ID,
        metadata_={
            "history": [
                {"query": "cosa e UMR", "answer": "User Mail Replica"},
                {"query": "e le limitazioni?", "answer": "Le limitazioni sono descritte qui"},
            ]
        },
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

    request = QueryRequest(
        query="continue our chat",
        options=QueryOptions(model="test-model"),
        conversation_id="conv-existing",
    )
    http_request = SimpleNamespace(
        method="POST",
        state=SimpleNamespace(
            tenant_id=TENANT, query_scopes=None, is_super_admin=False, api_key_id=API_KEY_ID
        ),
        headers={"X-User-ID": USER},
    )

    stream_session = _StreamSession(summary)
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker", lambda: _StreamSessionMaker(stream_session)
    )
    response = await _query_stream_impl(http_request=http_request, request=request)

    async for _chunk in response.body_iterator:
        pass

    assert "history" in retrieve_kwargs
    assert retrieve_kwargs["history"] == [
        {"role": "user", "content": "cosa e UMR"},
        {"role": "assistant", "content": "User Mail Replica"},
        {"role": "user", "content": "e le limitazioni?"},
        {"role": "assistant", "content": "Le limitazioni sono descritte qui"},
    ]


@pytest.mark.asyncio
async def test_x_user_id_spoof_cannot_read_another_keys_history(monkeypatch):
    """End-to-end regression for issue #72: an attacker authenticated with
    their own API key (api_key_id=OTHER_API_KEY_ID) sends X-User-ID equal to
    the victim's resolved identity and guesses the victim's conversation_id.
    Under the pre-fix `user_id`-keyed ownership check this would match and
    leak the victim's history into the attacker's retrieval context. Gating
    on the authenticated api_key_id instead must deny it regardless of what
    X-User-ID claims."""
    from src.api.config import settings as api_settings

    monkeypatch.setattr(
        api_settings, "enable_multiturn_history_reinjection", True, raising=False
    )

    victim_summary = SimpleNamespace(
        tenant_id=TENANT,
        api_key_id=API_KEY_ID,  # victim's real authenticated identity
        metadata_={"history": [{"query": "secret question", "answer": "secret answer"}]},
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

    request = QueryRequest(
        query="what was that secret question about?",
        options=QueryOptions(model="test-model"),
        conversation_id="victims-conversation-id",
    )
    # Attacker: authenticated with their OWN key, but spoofs X-User-ID to
    # equal whatever identity string the victim's row was saved under.
    http_request = SimpleNamespace(
        method="POST",
        state=SimpleNamespace(
            tenant_id=TENANT,
            query_scopes=None,
            is_super_admin=False,
            api_key_id=OTHER_API_KEY_ID,
        ),
        headers={"X-User-ID": USER},
    )

    stream_session = _StreamSession(victim_summary)
    monkeypatch.setattr(
        "src.api.deps._get_async_session_maker", lambda: _StreamSessionMaker(stream_session)
    )
    response = await _query_stream_impl(http_request=http_request, request=request)

    async for _chunk in response.body_iterator:
        pass

    assert "history" in retrieve_kwargs
    assert retrieve_kwargs.get("history") is None, (
        "Attacker with a spoofed X-User-ID must not receive the victim's conversation history"
    )


# =============================================================================
# _resolve_owned_summary — shared write-path helper unit tests
# =============================================================================


def test_resolve_owned_summary_none_returns_none():
    from src.api.routes.query import _resolve_owned_summary

    assert _resolve_owned_summary(None, TENANT, API_KEY_ID) is None


def test_resolve_owned_summary_caller_none_returns_none():
    """An unauthenticated caller must never update a legacy row."""
    from src.api.routes.query import _resolve_owned_summary

    existing = SimpleNamespace(id="c1", tenant_id=TENANT, api_key_id=None)
    assert _resolve_owned_summary(existing, TENANT, None) is None


def test_resolve_owned_summary_foreign_tenant_returns_none():
    from src.api.routes.query import _resolve_owned_summary

    existing = SimpleNamespace(id="c1", tenant_id="other-tenant", api_key_id=API_KEY_ID)
    assert _resolve_owned_summary(existing, TENANT, API_KEY_ID) is None


def test_resolve_owned_summary_foreign_api_key_returns_none():
    from src.api.routes.query import _resolve_owned_summary

    existing = SimpleNamespace(id="c1", tenant_id=TENANT, api_key_id=OTHER_API_KEY_ID)
    assert _resolve_owned_summary(existing, TENANT, API_KEY_ID) is None


def test_resolve_owned_summary_matching_key_returns_summary():
    from src.api.routes.query import _resolve_owned_summary

    existing = SimpleNamespace(id="c1", tenant_id=TENANT, api_key_id=API_KEY_ID)
    result = _resolve_owned_summary(existing, TENANT, API_KEY_ID)
    assert result is existing
    assert result.api_key_id == API_KEY_ID


def test_resolve_owned_summary_legacy_row_is_rejected():
    from src.api.routes.query import _resolve_owned_summary

    existing = SimpleNamespace(id="c1", tenant_id=TENANT, api_key_id=None)
    result = _resolve_owned_summary(existing, TENANT, API_KEY_ID)
    assert result is None
    assert existing.api_key_id is None
