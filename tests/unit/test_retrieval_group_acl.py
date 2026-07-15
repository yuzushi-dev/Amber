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
