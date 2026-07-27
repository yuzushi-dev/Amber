"""
Regression test for the hybrid-search score_threshold silent-drop bug.

MilvusVectorStore.hybrid_search() previously accepted no score_threshold
parameter at all, so a tenant's configured similarity_threshold was silently
ignored on the hybrid (dense+SPLADE) path even though the dense-only search()
honored it. This test exercises hybrid_search() against a stubbed Milvus
collection (no real Milvus server needed) and asserts:

- score_threshold=None (the default) keeps every candidate, unchanged from
  prior behavior.
- An explicit score_threshold drops candidates scoring below it.
"""

import pytest

from src.core.retrieval.infrastructure.vector_store.milvus import (
    MilvusConfig,
    MilvusVectorStore,
)


class _FakeEntity:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeHit:
    def __init__(self, score: float, **fields):
        self.score = score
        self.entity = _FakeEntity(fields)


class _FakeField:
    def __init__(self, name: str):
        self.name = name


class _FakeSchema:
    def __init__(self, fields):
        self.fields = fields


class _FakeCollection:
    """Stub standing in for a pymilvus Collection, just enough for hybrid_search()."""

    def __init__(self, hits: list[_FakeHit], sparse_field_name: str):
        self.schema = _FakeSchema([_FakeField(sparse_field_name)])
        self._hits = hits
        self.hybrid_search_calls: list[dict] = []

    def hybrid_search(self, **kwargs):
        self.hybrid_search_calls.append(kwargs)
        # pymilvus returns one "hits" list per query vector; we only ever send one.
        return [self._hits]


def _make_store(hits: list[_FakeHit]) -> MilvusVectorStore:
    store = MilvusVectorStore(MilvusConfig(dimensions=3))

    async def _noop_connect():
        return None

    store.connect = _noop_connect  # avoid any real Milvus connection
    store._collection = _FakeCollection(hits, MilvusVectorStore.FIELD_SPARSE_VECTOR)
    return store


@pytest.mark.asyncio
async def test_hybrid_search_default_none_keeps_all_candidates():
    hits = [
        _FakeHit(0.03, chunk_id="c1", document_id="d1", tenant_id="t1", content="a"),
        _FakeHit(0.001, chunk_id="c2", document_id="d1", tenant_id="t1", content="b"),
    ]
    store = _make_store(hits)

    results = await store.hybrid_search(
        dense_vector=[0.1, 0.2, 0.3],
        sparse_vector={0: 0.5},
        tenant_id="t1",
        limit=10,
    )

    assert [r.chunk_id for r in results] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_hybrid_search_explicit_threshold_drops_low_scores():
    hits = [
        _FakeHit(0.03, chunk_id="c1", document_id="d1", tenant_id="t1", content="a"),
        _FakeHit(0.001, chunk_id="c2", document_id="d1", tenant_id="t1", content="b"),
    ]
    store = _make_store(hits)

    results = await store.hybrid_search(
        dense_vector=[0.1, 0.2, 0.3],
        sparse_vector={0: 0.5},
        tenant_id="t1",
        limit=10,
        score_threshold=0.02,  # fusion scale, well below cosine-style values like 0.7
    )

    assert [r.chunk_id for r in results] == ["c1"]


@pytest.mark.asyncio
async def test_hybrid_search_zero_threshold_is_active_not_disabled():
    """Regression: score_threshold=0.0 must FILTER (keep scores >= 0), not be
    treated as falsy/'disabled'. A hit with a negative fused score is dropped."""
    hits = [
        _FakeHit(0.02, chunk_id="c1", document_id="d1", tenant_id="t1", content="a"),
        _FakeHit(-0.01, chunk_id="c2", document_id="d1", tenant_id="t1", content="b"),
    ]
    store = _make_store(hits)

    results = await store.hybrid_search(
        dense_vector=[0.1, 0.2, 0.3],
        sparse_vector={0: 0.5},
        tenant_id="t1",
        limit=10,
        score_threshold=0.0,
    )

    # With the old `if score_threshold and ...` guard, 0.0 was falsy -> no filter
    # -> both kept. The correct `is not None` guard drops the negative-score hit.
    assert [r.chunk_id for r in results] == ["c1"]
