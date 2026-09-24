from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fallback", ["components_missing", "sparse_missing", "hybrid_error"]
)
async def test_hybrid_fallback_preserves_document_and_collection_scope(fallback):
    store = MilvusVectorStore.__new__(MilvusVectorStore)
    store.config = SimpleNamespace(
        dimensions=3, collection_name="default", metric_type="COSINE"
    )
    store.connect = AsyncMock()
    store.search = AsyncMock(return_value=[])

    collection = MagicMock()
    store._collection = collection
    sparse_fields = [] if fallback == "sparse_missing" else [
        SimpleNamespace(name=store.FIELD_SPARSE_VECTOR)
    ]
    collection.schema.fields = sparse_fields
    if fallback == "hybrid_error":
        collection.hybrid_search.side_effect = RuntimeError("hybrid unavailable")

    milvus = {
        "AnnSearchRequest": None if fallback == "components_missing" else MagicMock(),
        "RRFRanker": None if fallback == "components_missing" else MagicMock(),
        "utility": MagicMock(),
        "Collection": MagicMock(return_value=collection),
    }
    milvus["utility"].has_collection.return_value = True

    with patch(
        "src.core.retrieval.infrastructure.vector_store.milvus._get_milvus",
        return_value=milvus,
    ):
        await store.hybrid_search(
            dense_vector=[0.1, 0.2, 0.3],
            sparse_vector={1: 0.5},
            tenant_id="tenant-a",
            document_ids=["commercial-doc"],
            limit=7,
            filters={"edition": "commercial"},
            collection_name="tenant-custom",
            exclude_document_ids=["non-ready-doc"],
        )

    store.search.assert_awaited_once_with(
        [0.1, 0.2, 0.3],
        "tenant-a",
        document_ids=["commercial-doc"],
        limit=7,
        filters={"edition": "commercial"},
        collection_name="tenant_custom",
        exclude_document_ids=["non-ready-doc"],
    )
