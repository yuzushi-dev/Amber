"""Regression tests for preserving existing artifacts on ingestion failure."""

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
        self.pending_generation_id = None
        self.content_hash = "test-hash"
        self.processing_attempt_id = None
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


class FakeDocumentRepositoryForFailure:
    """Drives process_document to the FAILED exception handler via a storage error."""

    def __init__(self, document: StubDocument) -> None:
        self.document = document
        self.saved: list[Any] = []
        self.generation = None

    async def get(self, document_id: str):
        return self.document

    async def update_status(
        self, document_id: str, status: str, old_status: str | None = None, attempt_id=None
    ) -> bool:
        self.document.status = status
        return True

    async def claim_processing_attempt(
        self, document_id, attempt_id, old_status, pending_generation_id
    ):
        self.document.processing_attempt_id = attempt_id
        return True

    async def release_processing_attempt(self, document_id, attempt_id):
        self.document.processing_attempt_id = None
        return True

    async def save(self, document) -> None:
        self.saved.append(document)

    async def save_generation(self, generation):
        self.generation = generation
        return generation

    async def get_generation(self, generation_id):
        return self.generation if self.generation and self.generation.id == generation_id else None

    async def mark_generation_failed(self, generation_id, error_message):
        self.generation.status = "failed"
        self.generation.error_message = error_message


class FakeUnitOfWork:
    async def commit(self) -> None:
        pass


class RaisingStorage:
    def get_file(self, storage_path: str):
        raise ValueError("storage is down")


@pytest.mark.asyncio
async def test_process_document_failure_preserves_existing_artifacts(monkeypatch):
    document = StubDocument(
        id="doc_7",
        tenant_id="tenant-1",
        status=DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_7/file.txt",
        filename="file.txt",
        content_hash="hash-7",
        metadata_={},
        pending_generation_id=None,
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
    assert vector_store.delete_calls == []
    assert neo4j_client.writes == []
