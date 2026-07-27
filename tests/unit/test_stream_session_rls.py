"""
Regression tests for the streaming RLS session leak fix.

`_query_stream_impl` (src/api/routes/query.py) receives a DB session that
already carries every RLS GUC set by `get_db_session` (src/api/deps.py).
Three blocks inside the SSE generator used to ignore that injected session
and open a brand-new bare one via `_get_async_session_maker()()`, which has
NONE of those GUCs set — causing the RLS-protected INSERT/SELECT on
`conversation_summaries` to fail (loudly for the two saves, silently — as an
empty SELECT — for the sticky-mode check).

These tests prove the fix without touching the DB: they drive
`_query_stream_impl` with fake service/session doubles and assert
(1) `_get_async_session_maker` is never called, and (2) the injected
`session` object is the one that receives the get/add/commit calls.

A `_Sentinel(BaseException)` is used to abort the generator at the exact
point under test — NOT `Exception`, because the surrounding code has
`except Exception` fallbacks (sticky-check swallows failures with a warning
log; the RAG-save block swallows with an error log) that would otherwise
hide a wrong-session bug behind a "test passed" result.
"""

from types import SimpleNamespace

import pytest

from src.api.routes.query import _query_stream_impl
from src.api.schemas.query import QueryOptions, QueryRequest


class _Sentinel(BaseException):
    """Escapes `except Exception` fallbacks to pinpoint exactly where the
    generator reached, without being swallowed as an ordinary error."""


def _headers(user_id: str = "tester"):
    return {"X-User-ID": user_id}


def _http_request(tenant_id: str = "tenant-x", conversation_id_scopes=None):
    return SimpleNamespace(
        method="POST",
        state=SimpleNamespace(
            tenant_id=tenant_id,
            query_scopes=conversation_id_scopes,
            is_super_admin=False,
        ),
        headers=_headers(),
    )


async def _drain(response):
    """`_query_stream_impl` is a coroutine returning a StreamingResponse;
    await it, then pump body_iterator to actually run the generator body."""
    async for _chunk in response.body_iterator:
        pass


class _BareSession:
    """Stands in for the old `_get_async_session_maker()()` bare session:
    fully functional, but carries none of the RLS GUCs. If the code under
    test still reaches for it, these calls succeed silently — which is
    exactly the old (buggy) behaviour we must NOT see after the fix."""

    def __init__(self, calls: list[str]):
        self._calls = calls

    async def get(self, *_args, **_kwargs):
        self._calls.append("bare.get")
        return None

    def add(self, _obj):
        self._calls.append("bare.add")

    async def commit(self):
        self._calls.append("bare.commit")


class _BareSessionCtx:
    def __init__(self, calls: list[str]):
        self._session = _BareSession(calls)

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_exc):
        return False


class _InjectedSession:
    """Stands in for the real request-scoped session: same object passed in
    via `session=` — has all the RLS GUCs set in real life. `.get`/`.commit`
    raise the sentinel once invoked, to prove control flow reached here."""

    def __init__(self, calls: list[str]):
        self.calls = calls

    async def get(self, model, pk):
        self.calls.append(("injected.get", model, pk))
        raise _Sentinel()

    def add(self, _obj):
        self.calls.append("injected.add")

    async def commit(self):
        self.calls.append("injected.commit")
        raise _Sentinel()


def _patch_services(monkeypatch):
    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_retrieval_service",
        lambda _session: SimpleNamespace(),
        raising=False,
    )
    monkeypatch.setattr(
        "src.amber_platform.composition_root.build_generation_service",
        lambda _session: SimpleNamespace(),
        raising=False,
    )


def _patch_bare_session_maker(monkeypatch, calls: list[str]):
    """Patches `_get_async_session_maker` to a working (but GUC-less) bare
    session factory, and returns a mock recording whether it was invoked.

    Real shape: `_get_async_session_maker()` returns a sessionmaker, and the
    buggy code calls it again — `_get_async_session_maker()()` — to open a
    session. So the mock itself must return a *callable* that in turn
    produces the async context manager.
    """
    from unittest.mock import MagicMock

    session_maker = lambda: _BareSessionCtx(calls)  # noqa: E731
    maker = MagicMock(side_effect=lambda: session_maker)
    monkeypatch.setattr("src.api.deps._get_async_session_maker", maker)
    return maker


@pytest.mark.asyncio
async def test_stream_uses_injected_session_for_conversation_save(monkeypatch):
    """RAG-save block (~:882-940 pre-fix): the streaming answer must be
    persisted through the session injected via Depends(get_db_session), not
    a fresh RLS-GUC-less session — otherwise the INSERT is rejected by the
    `conversation_summaries` RLS policy and streaming history is never
    persisted (reproduced on prod as InsufficientPrivilegeError)."""
    _patch_services(monkeypatch)

    bare_calls: list[str] = []
    injected_calls: list = []
    maker_mock = _patch_bare_session_maker(monkeypatch, bare_calls)

    async def fake_try_execute(**_kw):
        return None

    monkeypatch.setattr(
        "src.core.retrieval.application.query.structured_query.structured_executor.try_execute",
        fake_try_execute,
    )

    async def fake_generate_stream(**_kw):
        yield {"event": "token", "data": "Hello"}
        yield {
            "event": "sources",
            "data": [{"chunk_id": "c1", "document_id": "d1", "score": 0.9}],
        }
        yield {"event": "done", "data": {"model": "test-model", "provider": "test-provider"}}

    async def fake_retrieve(**_kw):
        return SimpleNamespace(chunks=[{"score": 0.9}], cache_hit=False)

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
        query="How do I enable alerting?",
        options=QueryOptions(model="test-model"),
        conversation_id=None,
    )

    injected = _InjectedSession(injected_calls)

    response = await _query_stream_impl(
        http_request=_http_request(),
        request=request,
        session=injected,
    )

    with pytest.raises(_Sentinel):
        await _drain(response)

    assert "injected.add" in injected.calls
    assert "injected.commit" in injected.calls
    assert bare_calls == [], "conversation save must not touch the bare (GUC-less) session"
    assert maker_mock.called is False, "_get_async_session_maker must never be invoked"


@pytest.mark.asyncio
async def test_sticky_check_uses_injected_session(monkeypatch):
    """Sticky-mode check (~:443 pre-fix): the SELECT on conversation_summaries
    must run through the injected (GUC-carrying) session. Under RLS without
    GUCs the SELECT doesn't error — it silently returns 0 rows — so an
    already-agent conversation never auto-switches back to agent mode."""
    _patch_services(monkeypatch)

    bare_calls: list[str] = []
    injected_calls: list = []
    maker_mock = _patch_bare_session_maker(monkeypatch, bare_calls)

    request = QueryRequest(
        query="continue our conversation",
        options=None,
        conversation_id="conv-123",
    )

    injected = _InjectedSession(injected_calls)

    response = await _query_stream_impl(
        http_request=_http_request(),
        request=request,
        session=injected,
    )

    with pytest.raises(_Sentinel):
        await _drain(response)

    get_calls = [c for c in injected.calls if isinstance(c, tuple) and c[0] == "injected.get"]
    assert len(get_calls) == 1
    assert get_calls[0][2] == "conv-123"
    assert bare_calls == [], "sticky-mode check must not touch the bare (GUC-less) session"
    assert maker_mock.called is False, "_get_async_session_maker must never be invoked"
