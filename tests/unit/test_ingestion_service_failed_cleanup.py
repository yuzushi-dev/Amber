"""
Tests for the FAILED-transition cleanup hook in IngestionService.

Covers issue #106's systemic fix: on every `-> FAILED` transition, partial
Milvus vectors and Neo4j graph data for the document must be cleaned up
best-effort, without ever masking the original ingestion error.
"""

from typing import Any

import pytest

from src.core.ingestion.application import ingestion_service as service_module
from src.core.state.machine import DocumentStatus


class _StubInitComponent:
    def __init__(self, *args, **kwargs) -> None:
        pass


@pytest.fixture(autouse=True)
def _stub_heavy_init_components(monkeypatch):
    """IngestionService.__init__ unconditionally constructs these; none of
    them are exercised by these tests, and EmbeddingService requires global
    settings to be configured, which isn't the case in unit tests."""
    monkeypatch.setattr(service_module, "SemanticChunker", _StubInitComponent)
    monkeypatch.setattr(service_module, "EmbeddingService", _StubInitComponent)
    monkeypatch.setattr(service_module, "GraphProcessor", _StubInitComponent)
    monkeypatch.setattr(service_module, "GraphEnricher", _StubInitComponent)


class StubDocument:
    def __init__(self, **kwargs) -> None:
        # Real `Document` always has `error_message` (normally None); this
        # file's StubDocument predates process_document's post-#110 stale
        # error clearing, which reads it unconditionally.
        self.error_message = None
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeVectorStore:
    def __init__(self, *, raise_on_delete: bool = False) -> None:
        self.delete_calls: list[tuple[str, str]] = []
        self.raise_on_delete = raise_on_delete

    async def delete_by_document(self, document_id: str, tenant_id: str) -> int:
        self.delete_calls.append((document_id, tenant_id))
        if self.raise_on_delete:
            raise RuntimeError("milvus unavailable")
        return 3


class FakeNeo4jClient:
    def __init__(
        self,
        *,
        affected_community_ids: list[str] | None = None,
        raise_on_read: bool = False,
        raise_on_write: bool = False,
    ) -> None:
        self.reads: list[tuple[str, dict]] = []
        self.writes: list[tuple[str, dict]] = []
        self.affected_community_ids = affected_community_ids or []
        self.raise_on_read = raise_on_read
        self.raise_on_write = raise_on_write

    async def execute_read(self, query: str, parameters: dict) -> list[dict]:
        self.reads.append((query, parameters))
        if self.raise_on_read:
            raise RuntimeError("neo4j read unavailable")
        return [{"ids": self.affected_community_ids}]

    async def execute_write(self, query: str, parameters: dict) -> None:
        self.writes.append((query, parameters))
        if self.raise_on_write:
            raise RuntimeError("neo4j write unavailable")


def make_service(*, vector_store: Any = None, neo4j_client: Any = None) -> Any:
    return service_module.IngestionService(
        document_repository=None,
        tenant_repository=None,
        unit_of_work=None,
        storage_client=None,
        neo4j_client=neo4j_client,
        vector_store=vector_store,
    )


@pytest.mark.asyncio
async def test_cleanup_deletes_milvus_vectors_and_neo4j_graph_data():
    vector_store = FakeVectorStore()
    neo4j_client = FakeNeo4jClient(affected_community_ids=["comm_1", "comm_2"])
    service = make_service(vector_store=vector_store, neo4j_client=neo4j_client)
    document = StubDocument(id="doc_1", tenant_id="tenant-1")

    await service._cleanup_failed_document_artifacts(document)

    assert vector_store.delete_calls == [("doc_1", "tenant-1")]
    assert len(neo4j_client.reads) == 1
    assert neo4j_client.reads[0][1] == {"document_id": "doc_1", "tenant_id": "tenant-1"}
    # Two writes expected: the chunk/entity delete, then the stale-marking write.
    assert len(neo4j_client.writes) == 2
    delete_query, delete_params = neo4j_client.writes[0]
    assert "DETACH DELETE ch" in delete_query
    assert delete_params == {"document_id": "doc_1", "tenant_id": "tenant-1"}
    stale_query, stale_params = neo4j_client.writes[1]
    assert "is_stale = true" in stale_query
    assert stale_params == {"tenant_id": "tenant-1", "ids": ["comm_1", "comm_2"]}


@pytest.mark.asyncio
async def test_delete_cypher_aggregates_document_wide_before_deleting():
    """
    Regression guard for a bug found and fixed on the prod #106 graph backfill:
    grouping `WITH c, collect(DISTINCT e) AS entities` (c non-aggregated) produces
    one row PER CHUNK, so an entity mentioned by two chunks of the SAME document
    could still see a live MENTIONS edge from the other, not-yet-deleted chunk's
    row when the orphan check ran, leaving it undeleted despite having zero
    mentions once the whole document's chunks were actually gone. The fix
    aggregates chunks and entities into single document-wide lists (both sides
    of the WITH aggregated, no grouping key) and deletes all chunks via FOREACH
    before any orphan check runs.
    """
    vector_store = FakeVectorStore()
    neo4j_client = FakeNeo4jClient()
    service = make_service(vector_store=vector_store, neo4j_client=neo4j_client)
    document = StubDocument(id="doc_multi", tenant_id="tenant-1")

    await service._cleanup_failed_document_artifacts(document)

    delete_query = neo4j_client.writes[0][0]
    assert "collect(DISTINCT c)" in delete_query
    assert "collect(DISTINCT e)" in delete_query
    assert "FOREACH" in delete_query
    # No leftover per-chunk grouping: the old buggy form aggregated only `e`
    # while leaving `c` as a bare grouping key.
    assert "WITH c, collect(DISTINCT e)" not in delete_query


@pytest.mark.asyncio
async def test_cleanup_skips_stale_marking_when_no_affected_communities():
    vector_store = FakeVectorStore()
    neo4j_client = FakeNeo4jClient(affected_community_ids=[])
    service = make_service(vector_store=vector_store, neo4j_client=neo4j_client)
    document = StubDocument(id="doc_2", tenant_id="tenant-1")

    await service._cleanup_failed_document_artifacts(document)

    # Only the chunk/entity delete write, no stale-marking write.
    assert len(neo4j_client.writes) == 1


@pytest.mark.asyncio
async def test_cleanup_swallows_milvus_error_and_still_runs_neo4j():
    vector_store = FakeVectorStore(raise_on_delete=True)
    neo4j_client = FakeNeo4jClient()
    service = make_service(vector_store=vector_store, neo4j_client=neo4j_client)
    document = StubDocument(id="doc_3", tenant_id="tenant-1")

    # Must not raise despite Milvus failing.
    await service._cleanup_failed_document_artifacts(document)

    assert vector_store.delete_calls == [("doc_3", "tenant-1")]
    assert len(neo4j_client.writes) == 1  # Neo4j cleanup still ran independently.


@pytest.mark.asyncio
async def test_cleanup_swallows_neo4j_read_error_without_raising():
    vector_store = FakeVectorStore()
    neo4j_client = FakeNeo4jClient(raise_on_read=True)
    service = make_service(vector_store=vector_store, neo4j_client=neo4j_client)
    document = StubDocument(id="doc_4", tenant_id="tenant-1")

    await service._cleanup_failed_document_artifacts(document)

    assert vector_store.delete_calls == [("doc_4", "tenant-1")]
    assert neo4j_client.writes == []  # Never reached the write step.


@pytest.mark.asyncio
async def test_cleanup_swallows_neo4j_write_error_without_raising():
    vector_store = FakeVectorStore()
    neo4j_client = FakeNeo4jClient(raise_on_write=True)
    service = make_service(vector_store=vector_store, neo4j_client=neo4j_client)
    document = StubDocument(id="doc_5", tenant_id="tenant-1")

    await service._cleanup_failed_document_artifacts(document)  # Must not raise.


@pytest.mark.asyncio
async def test_cleanup_noop_when_stores_are_none():
    service = make_service(vector_store=None, neo4j_client=None)
    document = StubDocument(id="doc_6", tenant_id="tenant-1")

    # No stores configured: nothing to call, nothing should raise.
    await service._cleanup_failed_document_artifacts(document)


@pytest.mark.asyncio
async def test_cleanup_can_use_the_attempt_vector_store_from_a_factory():
    attempt_store = FakeVectorStore()
    service = make_service(vector_store=None, neo4j_client=None)
    document = StubDocument(id="doc_factory", tenant_id="tenant-1")

    await service._cleanup_failed_document_artifacts(document, vector_store=attempt_store)

    assert attempt_store.delete_calls == [("doc_factory", "tenant-1")]


class FakeDocumentRepositoryForFailure:
    """Drives process_document to the FAILED exception handler via a storage error."""

    def __init__(self, document: StubDocument) -> None:
        self.document = document
        self.saved: list[Any] = []

    async def get(self, document_id: str):
        return self.document

    async def update_status(self, document_id: str, status: str, old_status: str | None = None) -> bool:
        self.document.status = status
        return True

    async def save(self, document) -> None:
        self.saved.append(document)


class FakeUnitOfWork:
    async def commit(self) -> None:
        pass


class RaisingStorage:
    def get_file(self, storage_path: str):
        raise ValueError("storage is down")


@pytest.mark.asyncio
async def test_process_document_failure_triggers_cleanup_and_reraises_original_error(monkeypatch):
    document = StubDocument(
        id="doc_7",
        tenant_id="tenant-1",
        status=DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_7/file.txt",
        filename="file.txt",
        metadata_={},
    )
    vector_store = FakeVectorStore()
    neo4j_client = FakeNeo4jClient()
    service = make_service(vector_store=vector_store, neo4j_client=neo4j_client)
    service.document_repository = FakeDocumentRepositoryForFailure(document)
    service.unit_of_work = FakeUnitOfWork()
    service.storage = RaisingStorage()

    with pytest.raises(ValueError, match="storage is down"):
        await service.process_document("doc_7")

    assert document.status == DocumentStatus.FAILED
    # The cleanup hook ran as part of FAILED handling.
    assert vector_store.delete_calls == [("doc_7", "tenant-1")]
    assert len(neo4j_client.writes) == 1


@pytest.mark.asyncio
async def test_process_document_reraises_original_error_even_if_cleanup_hook_itself_raises(monkeypatch):
    document = StubDocument(
        id="doc_8",
        tenant_id="tenant-1",
        status=DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_8/file.txt",
        filename="file.txt",
        metadata_={},
    )
    service = make_service(vector_store=None, neo4j_client=None)
    service.document_repository = FakeDocumentRepositoryForFailure(document)
    service.unit_of_work = FakeUnitOfWork()
    service.storage = RaisingStorage()

    async def _broken_cleanup(self, doc):
        raise RuntimeError("cleanup helper has a bug")

    monkeypatch.setattr(
        service_module.IngestionService, "_cleanup_failed_document_artifacts", _broken_cleanup
    )

    # The ORIGINAL ValueError must still propagate, not the cleanup helper's RuntimeError.
    with pytest.raises(ValueError, match="storage is down"):
        await service.process_document("doc_8")

    assert document.status == DocumentStatus.FAILED
