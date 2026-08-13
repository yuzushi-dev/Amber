"""
Regression test for the HNSW `ef` < `k` production bug.

Milvus rejects HNSW searches where the `ef` search param is not larger than
the requested result `limit` (k), failing with:

    MilvusException: (code=65535, message=fail to search on QueryNode ...:
    config={"ef":128,"k":150,"metric_type":"COSINE",...} out of range in
    json: ef(128) should be larger than k(150)

`ef` used to be hardcoded to 128 in both `search()` (dense) and
`hybrid_search()` (dense+sparse), so any query requesting more than ~128
results (e.g. reranker disabled + an LLM config with `max_top_k` > 128)
broke outright. `MilvusVectorStore._hnsw_ef(limit)` now derives `ef`
dynamically so it always stays larger than `limit`, regardless of how high
`limit` goes.

These tests exercise both search paths against a stubbed Milvus collection
(no real Milvus server needed).
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
    """Stub standing in for a pymilvus Collection, just enough for search()/hybrid_search()."""

    def __init__(self, hits: list[_FakeHit], sparse_field_name: str):
        self.schema = _FakeSchema([_FakeField(sparse_field_name)])
        self._hits = hits
        self.search_calls: list[dict] = []
        self.hybrid_search_calls: list[dict] = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [self._hits]

    def hybrid_search(self, **kwargs):
        self.hybrid_search_calls.append(kwargs)
        return [self._hits]


def _make_store(hits: list[_FakeHit]) -> MilvusVectorStore:
    store = MilvusVectorStore(MilvusConfig(dimensions=3))

    async def _noop_connect():
        return None

    store.connect = _noop_connect  # avoid any real Milvus connection
    store._collection = _FakeCollection(hits, MilvusVectorStore.FIELD_SPARSE_VECTOR)
    return store


class TestHnswEfHelper:
    """Unit coverage for the _hnsw_ef() helper itself."""

    def test_default_floor_for_small_limits(self):
        # Historical behavior preserved: limits well below the floor still
        # get ef=128 (limit + margin doesn't exceed the floor yet).
        assert MilvusVectorStore._hnsw_ef(10) == 128
        assert MilvusVectorStore._hnsw_ef(90) == 128

    def test_scales_above_floor_when_limit_exceeds_it(self):
        # This is the exact failing case from prod: limit(k)=150 > ef=128.
        ef = MilvusVectorStore._hnsw_ef(150)
        assert ef > 150, "ef must be strictly larger than k, or Milvus rejects the search"

    def test_always_larger_than_limit(self):
        for limit in (1, 127, 128, 129, 150, 500, 1000):
            assert MilvusVectorStore._hnsw_ef(limit) > limit


@pytest.mark.asyncio
async def test_search_ef_scales_with_limit_above_128():
    """Dense search(): ef must stay larger than limit even when limit > 128."""
    hits = [_FakeHit(0.9, chunk_id="c1", document_id="d1", tenant_id="t1", content="a")]
    store = _make_store(hits)

    await store.search(
        query_vector=[0.1, 0.2, 0.3],
        tenant_id="t1",
        limit=150,
    )

    assert len(store._collection.search_calls) == 1
    search_params = store._collection.search_calls[0]["param"]
    ef = search_params["params"]["ef"]
    assert ef > 150, f"ef={ef} must be larger than k=150 (Milvus HNSW constraint)"


@pytest.mark.asyncio
async def test_search_ef_default_unchanged_for_small_limit():
    """Dense search(): small limits keep the historical ef=128 default."""
    hits = [_FakeHit(0.9, chunk_id="c1", document_id="d1", tenant_id="t1", content="a")]
    store = _make_store(hits)

    await store.search(
        query_vector=[0.1, 0.2, 0.3],
        tenant_id="t1",
        limit=10,
    )

    search_params = store._collection.search_calls[0]["param"]
    assert search_params["params"]["ef"] == 128


@pytest.mark.asyncio
async def test_hybrid_search_ef_scales_with_limit_above_128():
    """hybrid_search(): dense AnnSearchRequest's ef must stay larger than limit."""
    hits = [_FakeHit(0.9, chunk_id="c1", document_id="d1", tenant_id="t1", content="a")]
    store = _make_store(hits)

    await store.hybrid_search(
        dense_vector=[0.1, 0.2, 0.3],
        sparse_vector={0: 0.5},
        tenant_id="t1",
        limit=150,
    )

    assert len(store._collection.hybrid_search_calls) == 1
    reqs = store._collection.hybrid_search_calls[0]["reqs"]
    dense_req = reqs[0]  # dense AnnSearchRequest is built/sent first
    ef = dense_req.param["params"]["ef"]
    assert ef > 150, f"ef={ef} must be larger than k=150 (Milvus HNSW constraint)"


@pytest.mark.asyncio
async def test_hybrid_search_ef_default_unchanged_for_small_limit():
    """hybrid_search(): small limits keep the historical ef=128 default."""
    hits = [_FakeHit(0.9, chunk_id="c1", document_id="d1", tenant_id="t1", content="a")]
    store = _make_store(hits)

    await store.hybrid_search(
        dense_vector=[0.1, 0.2, 0.3],
        sparse_vector={0: 0.5},
        tenant_id="t1",
        limit=10,
    )

    reqs = store._collection.hybrid_search_calls[0]["reqs"]
    dense_req = reqs[0]
    assert dense_req.param["params"]["ef"] == 128
