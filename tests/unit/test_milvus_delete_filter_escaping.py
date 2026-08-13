import json
from types import SimpleNamespace

import pytest

from src.core.retrieval.infrastructure.vector_store.milvus import MilvusVectorStore


class RecordingCollection:
    def __init__(self) -> None:
        self.expressions: list[str] = []

    def delete(self, *, expr: str):
        self.expressions.append(expr)
        return SimpleNamespace(delete_count=0)

    def flush(self) -> None:
        pass


@pytest.mark.asyncio
async def test_delete_by_document_quotes_filter_values(monkeypatch):
    store = MilvusVectorStore()
    store._collection = RecordingCollection()

    async def connected() -> None:
        pass

    monkeypatch.setattr(store, "connect", connected)
    document_id = 'doc" || tenant_id != "default'
    tenant_id = 'tenant" || document_id != "doc'

    await store.delete_by_document(document_id, tenant_id)

    assert store._collection.expressions == [
        f"document_id == {json.dumps(document_id)} && tenant_id == {json.dumps(tenant_id)}"
    ]


@pytest.mark.asyncio
async def test_delete_by_tenant_quotes_filter_value(monkeypatch):
    store = MilvusVectorStore()
    store._collection = RecordingCollection()

    async def connected() -> None:
        pass

    monkeypatch.setattr(store, "connect", connected)
    tenant_id = 'tenant" || tenant_id != "safe'

    await store.delete_by_tenant(tenant_id)

    assert store._collection.expressions == [f"tenant_id == {json.dumps(tenant_id)}"]


@pytest.mark.asyncio
async def test_delete_chunks_quotes_ids_and_tenant(monkeypatch):
    store = MilvusVectorStore()
    store._collection = RecordingCollection()

    async def connected() -> None:
        pass

    monkeypatch.setattr(store, "connect", connected)
    chunk_ids = ['chunk" || tenant_id != "safe']
    tenant_id = 'tenant" || chunk_id != "safe'

    await store.delete_chunks(chunk_ids, tenant_id)

    assert store._collection.expressions == [
        f"chunk_id in [{json.dumps(chunk_ids[0])}] && tenant_id == {json.dumps(tenant_id)}"
    ]
