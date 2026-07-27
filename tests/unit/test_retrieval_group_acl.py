"""Regression test: group ACL must be enforced on own-tenant vector/graph
retrieval even when no candidate document set was pre-computed.

Before the fix, `_resolve_vector_targets` / `_resolve_graph_targets` only
applied the group allowlist when `candidate_document_ids` was not None or the
scope was a shared tenant. For the common own-tenant, no-candidate query this
left the target's document filter as None, so Milvus (tenant-filter only, no
group ACL) returned every chunk in the tenant — leaking documents the user's
groups were never granted. The endpoint that views a document directly *does*
enforce the group ACL, hence the 404 users hit after seeing such a source.
"""

import asyncio

from src.core.retrieval.application.retrieval_service import RetrievalService
from src.core.tenants.application.query_scopes import QueryScopes, resolve_query_scopes


def test_resolve_query_scopes_threads_group_state():
    # P1 regression: the auth path must be able to carry group membership +
    # enforcement into QueryScopes, else retrieval's group ACL stays dormant.
    scopes = resolve_query_scopes("default", group_ids=["g1", "g2"], enforce_groups=True)
    assert scopes.enforce_groups is True
    assert scopes.group_ids == ["g1", "g2"]
    # Default (no group context) keeps enforcement off.
    bare = resolve_query_scopes("default")
    assert bare.enforce_groups is False
    assert bare.group_ids == []


class _FakeRepo:
    """list_visible_document_ids returns whatever the group ACL would allow."""

    def __init__(self, allowed):
        self._allowed = allowed
        self.called_with = None

    async def list_visible_document_ids(
        self, viewer_tenant_id, owner_tenant_id, candidate_document_ids=None,
        group_ids=None, enforce_groups=False,
    ):
        self.called_with = {
            "enforce_groups": enforce_groups,
            "group_ids": group_ids,
            "candidate": candidate_document_ids,
        }
        return list(self._allowed)


def _service(repo):
    svc = object.__new__(RetrievalService)  # bypass heavy __init__
    svc.document_repository = repo

    async def _fake_collection(_tenant_id):
        return "col_default"

    svc._resolve_active_collection = _fake_collection  # type: ignore[attr-defined]
    return svc


def _scopes(enforce_groups):
    return QueryScopes(
        effective_tenant_id="default",
        vector_scopes=["default"],
        graph_scopes=["default"],
        shared_document_owner_tenants=[],
        group_ids=["grp_eng"],
        enforce_groups=enforce_groups,
    )


def test_own_tenant_enforced_applies_allowlist_without_candidate():
    repo = _FakeRepo(["doc_granted"])
    svc = _service(repo)
    targets = asyncio.run(
        svc._resolve_vector_targets(
            viewer_tenant_id="default",
            query_scopes=_scopes(enforce_groups=True),
            candidate_document_ids=None,
        )
    )
    assert repo.called_with is not None, "group ACL must be consulted (fail closed)"
    assert repo.called_with["enforce_groups"] is True
    assert len(targets) == 1
    assert targets[0].document_ids == ["doc_granted"]  # filtered, NOT None


def test_own_tenant_enforced_no_grants_yields_no_target():
    repo = _FakeRepo([])  # user's groups grant nothing
    svc = _service(repo)
    targets = asyncio.run(
        svc._resolve_vector_targets(
            viewer_tenant_id="default",
            query_scopes=_scopes(enforce_groups=True),
            candidate_document_ids=None,
        )
    )
    assert targets == [], "no grants => no searchable target (fail closed, no leak)"


def test_own_tenant_not_enforced_keeps_open_scope():
    # Tenant not using group enforcement: behaviour unchanged, no allowlist needed.
    repo = _FakeRepo(["should_not_be_used"])
    svc = _service(repo)
    targets = asyncio.run(
        svc._resolve_vector_targets(
            viewer_tenant_id="default",
            query_scopes=_scopes(enforce_groups=False),
            candidate_document_ids=None,
        )
    )
    assert repo.called_with is None, "no ACL query when enforcement is off"
    assert len(targets) == 1
    assert targets[0].document_ids is None  # unrestricted within tenant


def test_graph_path_mirrors_vector():
    repo = _FakeRepo([])
    svc = _service(repo)
    targets = asyncio.run(
        svc._resolve_graph_targets(
            viewer_tenant_id="default",
            query_scopes=_scopes(enforce_groups=True),
            candidate_document_ids=None,
        )
    )
    assert targets == [], "graph retrieval must fail closed too"


if __name__ == "__main__":
    test_own_tenant_enforced_applies_allowlist_without_candidate()
    test_own_tenant_enforced_no_grants_yields_no_target()
    test_own_tenant_not_enforced_keeps_open_scope()
    test_graph_path_mirrors_vector()
    print("ok")


def test_structured_fast_path_skipped_when_group_enforced(monkeypatch):
    """SECURITY regression: the STRUCTURED Cypher fast-path has no group ACL,
    so it must be skipped when the caller has group enforcement on (fall through
    to the ACL-enforced RAG path). Otherwise a group-restricted user enumerates
    documents/entities their groups were never granted."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.core.retrieval.application import use_cases_query as ucq
    from src.core.retrieval.application.query import structured_query

    # Record whether the structured executor is consulted.
    try_exec = AsyncMock(return_value=SimpleNamespace(
        success=True, query_type=SimpleNamespace(value="LIST_DOCUMENTS"),
        count=999, data=[], execution_time_ms=1.0,
    ))
    monkeypatch.setattr(structured_query.structured_executor, "try_execute", try_exec)

    uc = object.__new__(ucq.QueryUseCase)

    class _Sentinel(Exception):
        pass

    # Anything past the structured block trips this, so we can assert we got there.
    uc.metrics = SimpleNamespace(track_query=lambda **k: (_ for _ in ()).throw(_Sentinel()))
    uc.retrieval_service = None
    uc.generation_service = None

    req = SimpleNamespace(query="list all documents", options=None, conversation_id=None)

    # enforce_groups=True -> structured MUST be skipped, control reaches RAG (Sentinel).
    enforced = resolve_query_scopes("default", group_ids=["g1"], enforce_groups=True)
    state = SimpleNamespace(query_scopes=enforced, is_super_admin=False)
    try:
        asyncio.run(uc.execute(request=req, tenant_id="default",
                               http_request_state=state, user_id="u1"))
    except _Sentinel:
        pass
    assert try_exec.await_count == 0, "structured fast-path must NOT run under group enforcement"

    # enforce_groups=False -> structured runs and short-circuits with its response.
    open_scopes = resolve_query_scopes("default")
    state2 = SimpleNamespace(query_scopes=open_scopes, is_super_admin=False)
    resp = asyncio.run(uc.execute(request=req, tenant_id="default",
                                  http_request_state=state2, user_id="u1"))
    assert try_exec.await_count == 1
    assert getattr(resp, "count", None) == 999


def test_structured_mode_refused_when_group_enforced(monkeypatch):
    """SECURITY regression: SearchMode.STRUCTURED runs tenant-scoped Cypher with
    no group ACL, and options.search_mode is a public request field the router
    honours verbatim — so the guard in use_cases_query alone is bypassable with
    {"options": {"search_mode": "structured"}}. retrieve() must refuse the mode
    under group enforcement and fall through to the ACL-enforced vector path."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.core.retrieval.application.query import structured_query as sq
    from src.shared.kernel.models.query import QueryOptions, SearchMode

    # BaseException: the search block catches Exception and falls back, which
    # would swallow a plain sentinel.
    class _ReachedVectorPath(BaseException):
        pass

    try_exec = AsyncMock(return_value=SimpleNamespace(
        success=True, query_type=SimpleNamespace(value="LIST_DOCUMENTS"),
        count=999, data=[], execution_time_ms=1.0,
    ))
    monkeypatch.setattr(sq.structured_executor, "try_execute", try_exec)

    svc = object.__new__(RetrievalService)
    svc.config = SimpleNamespace(top_k=5)
    svc.document_repository = object()  # no taxonomy method -> skip that branch
    svc.router = SimpleNamespace(route=AsyncMock(return_value=SearchMode.STRUCTURED))

    async def _tenant_config(_tid):
        return {}

    async def _targets(**_kw):
        return []

    reached = {"vector": False}

    async def _vector_search(**_kw):
        reached["vector"] = True
        raise _ReachedVectorPath()

    svc._get_effective_tenant_config = _tenant_config       # type: ignore[attr-defined]
    svc._resolve_vector_targets = _targets                  # type: ignore[attr-defined]
    svc._execute_vector_search = _vector_search             # type: ignore[attr-defined]

    opts = QueryOptions(search_mode=SearchMode.STRUCTURED)

    def _retrieve(scopes):
        """Run retrieve() far enough to observe the routing decision. Anything
        past the search block (caching, circuit breaker, ...) is out of scope for
        this unit and is allowed to blow up."""
        try:
            asyncio.run(svc.retrieve(query="list all documents", tenant_id="default",
                                     options=opts, query_scopes=scopes))
        except BaseException:  # noqa: BLE001 - see docstring
            pass

    # enforce_groups=True -> STRUCTURED refused, control reaches the vector path.
    _retrieve(_scopes(True))
    assert try_exec.await_count == 0, "STRUCTURED must NOT run under group enforcement"
    assert reached["vector"], "refused STRUCTURED must fall through to vector search"

    # enforce_groups=False -> unchanged behaviour, the executor is consulted.
    _retrieve(_scopes(False))
    assert try_exec.await_count == 1, "STRUCTURED must still run without enforcement"


def test_stream_structured_precheck_skipped_when_group_enforced(monkeypatch):
    """SECURITY regression: the SSE pre-check is a second entry point to the same
    ACL-less Cypher, reachable by typing "list all documents" in the chat. It must
    honour enforce_groups exactly like the non-stream path."""
    from types import SimpleNamespace

    from src.api.routes import query as query_routes
    from src.core.retrieval.application.query import structured_query as sq

    class _ExecutorCalled(BaseException):
        pass

    calls = {"n": 0}

    async def _try_execute(**_kw):
        calls["n"] += 1
        raise _ExecutorCalled()  # escapes the block's `except Exception`

    monkeypatch.setattr(sq.structured_executor, "try_execute", _try_execute)

    # The stream builds its services before the structured pre-check; with no real
    # DB session that raises 503 and we'd never reach the code under test.
    from src.amber_platform import composition_root

    monkeypatch.setattr(composition_root, "build_retrieval_service",
                        lambda _session: SimpleNamespace(), raising=False)
    monkeypatch.setattr(composition_root, "build_generation_service",
                        lambda _session: SimpleNamespace(), raising=False)

    def _drive(scopes):
        """_query_stream_impl is a coroutine returning a StreamingResponse, so we
        await it and then pump its body_iterator until the executor is hit or the
        generator sails past the structured block into the RAG path (which this
        unit does not wire up)."""
        http_request = SimpleNamespace(
            method="POST",
            state=SimpleNamespace(tenant_id="default", query_scopes=scopes,
                                  is_super_admin=False),
            headers={"X-User-ID": "u1"},
        )
        req = SimpleNamespace(query="list all documents", options=None,
                              conversation_id=None)

        async def _pump():
            resp = await query_routes._query_stream_impl(http_request, request=req)
            async for _chunk in resp.body_iterator:
                pass

        try:
            asyncio.run(_pump())
        except _ExecutorCalled:
            return "executor_called"
        except BaseException:  # noqa: BLE001 - see docstring
            return "past_structured"
        return "past_structured"

    assert _drive(_scopes(True)) == "past_structured"
    assert calls["n"] == 0, "SSE structured pre-check must NOT run under group enforcement"

    assert _drive(_scopes(False)) == "executor_called"
    assert calls["n"] == 1
