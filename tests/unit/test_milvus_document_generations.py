import json
from types import SimpleNamespace

import pytest

from src.core.retrieval.infrastructure.vector_store.milvus import MilvusConfig, MilvusVectorStore


class _Collection:
    def __init__(self):
        self.expressions: list[str] = []
        self.upserts: list[list[dict]] = []

    def delete(self, *, expr: str):
        self.expressions.append(expr)
        return SimpleNamespace(delete_count=1)

    def flush(self):
        pass

    def upsert(self, rows: list[dict]):
        self.upserts.append(rows)

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        entity = {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "tenant_id": "tenant-1",
            "content": "text",
            "generation_id": "gen-1",
        }
        return [[SimpleNamespace(score=0.9, entity=SimpleNamespace(get=entity.get))]]


@pytest.mark.asyncio
async def test_delete_by_generation_scopes_and_quotes_every_identifier(monkeypatch):
    store = MilvusVectorStore()
    store._collection = _Collection()

    async def connected() -> None:
        pass

    monkeypatch.setattr(store, "connect", connected)
    document_id = 'doc" || tenant_id != "safe'
    tenant_id = 'tenant" || generation_id != "safe'
    generation_id = 'gen" || document_id != "safe'

    await store.delete_by_generation(document_id, tenant_id, generation_id)

    assert store._collection.expressions == [
        " && ".join(
            [
                f"document_id == {json.dumps(document_id)}",
                f"tenant_id == {json.dumps(tenant_id)}",
                f"generation_id == {json.dumps(generation_id)}",
            ]
        )
    ]


@pytest.mark.asyncio
async def test_upsert_and_search_round_trip_generation_id(monkeypatch):
    store = MilvusVectorStore(MilvusConfig(dimensions=2))
    collection = _Collection()
    store._collection = collection

    async def connected() -> None:
        pass

    monkeypatch.setattr(store, "connect", connected)

    await store.upsert_chunks(
        [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "tenant_id": "tenant-1",
                "content": "text",
                "embedding": [0.1, 0.2],
                "generation_id": "gen-1",
            }
        ]
    )

    assert collection.upserts[0][0]["generation_id"] == "gen-1"

    results = await store.search([0.1, 0.2], "tenant-1")

    assert "generation_id" in collection.search_kwargs["output_fields"]
    assert results[0].generation_id == "gen-1"
