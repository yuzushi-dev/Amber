"""Unit tests for the non-READY document blocklist (Part A of the
ingestion-dedup-and-ready-filter fix).

Root cause: Milvus has no document-status field, so retrieval can surface
chunks belonging to FAILED/duplicate documents. The fix excludes a small,
stable blocklist (non-READY documents that still have indexed chunks) via a
`NOT ... IN [...]` clause inside the store's native query expression - NOT a
post-filter, which would consume `limit` before excluding anything and could
return fewer than `limit` results even with enough eligible chunks available.
"""

import asyncio
import re

import pytest

from src.core.retrieval.application.retrieval_service import (
    GraphSearchTarget,
    RetrievalService,
    VectorSearchTarget,
)
from src.core.retrieval.application.search.graph import GraphSearcher
from src.core.retrieval.infrastructure.vector_store.milvus import MilvusConfig, MilvusVectorStore
from src.core.tenants.application.query_scopes import QueryScopes

# ---------------------------------------------------------------------------
# Test 5: vector search excludes non-READY chunks via the Milvus expr itself
# ---------------------------------------------------------------------------


class _FakeEntity:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeHit:
    def __init__(self, score: float, **fields):
        self.score = score
        self.entity = _FakeEntity(fields)


def _extract_excluded_ids(expr: str) -> set[str]:
    """Pull the quoted ids out of a `!(document_id in ["a", "b"])` clause."""
    match = re.search(
        r"!\(" + re.escape(MilvusVectorStore.FIELD_DOCUMENT_ID) + r"\s+in\s+\[([^\]]*)\]\)",
        expr,
    )
    if not match:
        return set()
    return {piece.strip().strip('"') for piece in match.group(1).split(",") if piece.strip()}


class _RankedFakeCollection:
    """Stand-in for a pymilvus Collection that behaves like real Milvus:
    the `expr` filter is applied to the FULL ranked candidate pool BEFORE
    `limit` truncates it - not after. This is exactly the distinction the
    fix depends on (expr-side exclusion vs. a post-filter that would
    silently return fewer than `limit` results)."""

    def __init__(self, all_hits: list[_FakeHit]):
        self._all_hits = all_hits  # already rank-ordered (best score first)
        self.last_expr: str | None = None

    def search(self, *, data, anns_field, param, limit, expr, output_fields, consistency_level):
        self.last_expr = expr
        tenant_match = re.search(r'tenant_id == "([^"]+)"', expr)
        tenant_id = tenant_match.group(1) if tenant_match else None
        excluded = _extract_excluded_ids(expr)

        filtered = [
            hit
            for hit in self._all_hits
            if hit.entity.get(MilvusVectorStore.FIELD_TENANT_ID) == tenant_id
            and hit.entity.get(MilvusVectorStore.FIELD_DOCUMENT_ID) not in excluded
        ]
        return [filtered[:limit]]


def _make_store(all_hits: list[_FakeHit]) -> tuple[MilvusVectorStore, _RankedFakeCollection]:
    store = MilvusVectorStore(MilvusConfig(dimensions=3))

    async def _noop_connect():
        return None

    store.connect = _noop_connect
    collection = _RankedFakeCollection(all_hits)
    store._collection = collection
    return store, collection


@pytest.mark.asyncio
async def test_vector_search_excludes_non_ready_chunks():
    # 3 non-ready chunks rank ABOVE the 5 ready ones. A naive post-filter
    # (apply limit=5 first, then drop non-ready) would return only 2 results.
    # Filtering inside the expr must still saturate top_k=5 with READY chunks.
    hits = [
        _FakeHit(0.99, chunk_id="c-bad-1", document_id="doc-failed-1", tenant_id="t1", content="x"),
        _FakeHit(0.98, chunk_id="c-bad-2", document_id="doc-failed-1", tenant_id="t1", content="x"),
        _FakeHit(0.97, chunk_id="c-bad-3", document_id="doc-failed-2", tenant_id="t1", content="x"),
        _FakeHit(0.96, chunk_id="c-ok-1", document_id="doc-ready-1", tenant_id="t1", content="x"),
        _FakeHit(0.95, chunk_id="c-ok-2", document_id="doc-ready-1", tenant_id="t1", content="x"),
        _FakeHit(0.94, chunk_id="c-ok-3", document_id="doc-ready-2", tenant_id="t1", content="x"),
        _FakeHit(0.93, chunk_id="c-ok-4", document_id="doc-ready-2", tenant_id="t1", content="x"),
        _FakeHit(0.92, chunk_id="c-ok-5", document_id="doc-ready-3", tenant_id="t1", content="x"),
    ]
    store, collection = _make_store(hits)

    results = await store.search(
        query_vector=[0.1, 0.2, 0.3],
        tenant_id="t1",
        limit=5,
        exclude_document_ids=["doc-failed-1", "doc-failed-2"],
    )

    assert collection.last_expr is not None
    assert "!(document_id in [" in collection.last_expr, (
        "exclusion must be part of the Milvus expr, not a Python-side post-filter"
    )

    assert len(results) == 5, "enough READY chunks exist; top_k must still be saturated"
    returned_ids = {r.chunk_id for r in results}
    assert returned_ids == {"c-ok-1", "c-ok-2", "c-ok-3", "c-ok-4", "c-ok-5"}
    assert returned_ids.isdisjoint({"c-bad-1", "c-bad-2", "c-bad-3"})


# ---------------------------------------------------------------------------
# Test 6: graph search excludes non-READY chunks (mirrors the vector path)
# ---------------------------------------------------------------------------


class _FakeNeo4j:
    def __init__(self):
        self.execute_read_calls: list[tuple[str, dict]] = []

    async def execute_read(self, query, params):
        self.execute_read_calls.append((query, params))
        return []


@pytest.mark.asyncio
async def test_graph_search_excludes_non_ready_chunks():
    neo4j = _FakeNeo4j()
    searcher = GraphSearcher(neo4j)

    await searcher.search_by_entities(
        entity_ids=["e1"],
        tenant_id="t1",
        excluded_doc_ids=["doc-failed-1"],
    )

    query, params = neo4j.execute_read_calls[-1]
    assert "NOT c.document_id IN $excluded_doc_ids" in query
    assert params["excluded_doc_ids"] == ["doc-failed-1"]

    neo4j2 = _FakeNeo4j()
    searcher2 = GraphSearcher(neo4j2)
    await searcher2.search_by_neighbors(
        chunk_ids=["c1"],
        tenant_id="t1",
        excluded_doc_ids=["doc-failed-1"],
    )
    query2, params2 = neo4j2.execute_read_calls[-1]
    assert "NOT neighbor.document_id IN $excluded_doc_ids" in query2
    assert params2["excluded_doc_ids"] == ["doc-failed-1"]


@pytest.mark.asyncio
async def test_graph_search_omits_exclusion_clause_when_not_requested():
    neo4j = _FakeNeo4j()
    searcher = GraphSearcher(neo4j)
    await searcher.search_by_entities(entity_ids=["e1"], tenant_id="t1")
    query, params = neo4j.execute_read_calls[-1]
    assert "excluded_doc_ids" not in params
    assert "NOT c.document_id IN $excluded_doc_ids" not in query


# ---------------------------------------------------------------------------
# Structural wiring: _resolve_vector_targets / _resolve_graph_targets always
# resolve the blocklist regardless of ACL settings, and forward it onto the
# VectorSearchTarget/GraphSearchTarget dataclasses.
# ---------------------------------------------------------------------------


class _FakeRepoWithBlocklist:
    def __init__(self, blocklist: list[str]):
        self._blocklist = blocklist
        self.calls: list[str] = []

    async def list_non_ready_document_ids_with_chunks(self, tenant_id: str):
        self.calls.append(tenant_id)
        return list(self._blocklist)


def _service(repo) -> RetrievalService:
    svc = object.__new__(RetrievalService)  # bypass heavy __init__
    svc.document_repository = repo

    async def _fake_collection(_tenant_id):
        return "col_default"

    svc._resolve_active_collection = _fake_collection  # type: ignore[attr-defined]
    return svc


def _scopes() -> QueryScopes:
    return QueryScopes(
        effective_tenant_id="default",
        vector_scopes=["default"],
        graph_scopes=["default"],
        shared_document_owner_tenants=[],
        group_ids=[],
        enforce_groups=False,
    )


def test_resolve_vector_targets_always_resolves_blocklist():
    repo = _FakeRepoWithBlocklist(["doc-failed-1", "doc-failed-2"])
    svc = _service(repo)

    targets = asyncio.run(
        svc._resolve_vector_targets(
            viewer_tenant_id="default",
            query_scopes=_scopes(),
            candidate_document_ids=None,
        )
    )

    assert repo.calls == ["default"]
    assert len(targets) == 1
    assert isinstance(targets[0], VectorSearchTarget)
    assert targets[0].exclude_document_ids == ["doc-failed-1", "doc-failed-2"]


def test_resolve_graph_targets_always_resolves_blocklist():
    repo = _FakeRepoWithBlocklist(["doc-failed-3"])
    svc = _service(repo)

    targets = asyncio.run(
        svc._resolve_graph_targets(
            viewer_tenant_id="default",
            query_scopes=_scopes(),
            candidate_document_ids=None,
        )
    )

    assert len(targets) == 1
    assert isinstance(targets[0], GraphSearchTarget)
    assert targets[0].excluded_doc_ids == ["doc-failed-3"]


def test_resolve_vector_targets_degrades_gracefully_without_repo_support():
    """Repos that don't implement the new method (older fakes/mocks) must not
    break retrieval - no exclusion applied, matching pre-fix behavior."""

    class _RepoWithoutMethod:
        pass

    svc = _service(_RepoWithoutMethod())
    targets = asyncio.run(
        svc._resolve_vector_targets(
            viewer_tenant_id="default",
            query_scopes=_scopes(),
            candidate_document_ids=None,
        )
    )
    assert len(targets) == 1
    assert targets[0].exclude_document_ids is None
