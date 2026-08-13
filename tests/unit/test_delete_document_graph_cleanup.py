from types import SimpleNamespace

import pytest

from src.core.ingestion.application.use_cases_documents import (
    DeleteDocumentRequest,
    DeleteDocumentUseCase,
)


class FakeResult:
    def scalars(self):
        return self

    def first(self):
        return SimpleNamespace(
            tenant_id="tenant-1",
            storage_path="tenant-1/doc-1/file.txt",
        )


class FakeSession:
    async def execute(self, _query):
        return FakeResult()

    async def delete(self, _document):
        return None

    async def commit(self):
        return None


class FakeGraph:
    def __init__(self):
        self.reads = []
        self.writes = []

    async def execute_read(self, query, parameters=None):
        self.reads.append((query, parameters))
        return []

    async def execute_write(self, query, parameters=None):
        self.writes.append((query, parameters))
        return []


class FakeVectorStore:
    async def delete_by_document(self, _document_id, _tenant_id):
        return None

    async def disconnect(self):
        return None


class FakeStorage:
    def delete_file(self, _path):
        return None


@pytest.mark.asyncio
async def test_delete_document_collects_all_chunks_before_orphan_sweep():
    graph = FakeGraph()
    use_case = DeleteDocumentUseCase(
        session=FakeSession(),
        storage=FakeStorage(),
        graph_client=graph,
        vector_store_factory=lambda _tenant_id: FakeVectorStore(),
    )

    await use_case.execute(DeleteDocumentRequest(document_id="doc-1", tenant_id="tenant-1"))

    primary_query = graph.writes[0][0]
    assert "collect(DISTINCT c) AS chunks" in primary_query
    assert "collect(DISTINCT e) AS entities" in primary_query
    assert "FOREACH (ch IN chunks | DETACH DELETE ch)" in primary_query
    assert "WITH d, c, collect(DISTINCT e)" not in primary_query


@pytest.mark.asyncio
async def test_delete_document_keeps_shared_entities_and_cleans_property_only_chunks(caplog):
    graph = FakeGraph()
    use_case = DeleteDocumentUseCase(
        session=FakeSession(),
        storage=FakeStorage(),
        graph_client=graph,
        vector_store_factory=lambda _tenant_id: FakeVectorStore(),
    )

    await use_case.execute(DeleteDocumentRequest(document_id="doc-1", tenant_id="tenant-1"))

    orphan_entity_queries = [query for query, _ in graph.writes if "MATCH (e:Entity" in query]
    assert orphan_entity_queries
    assert all("tenant_id" in query for query in orphan_entity_queries)
    orphan_chunk_queries = [query for query, _ in graph.writes if "MATCH (c:Chunk {document_id" in query]
    assert orphan_chunk_queries
    assert all("tenant_id: $tenant_id" in query for query in orphan_chunk_queries)
    assert "graph_document_cleanup_failed" not in caplog.text
