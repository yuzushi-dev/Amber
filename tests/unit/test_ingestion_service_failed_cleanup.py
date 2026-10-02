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

    async def rollback(self) -> None:
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


class PoisonedSessionUnitOfWork:
    """Mimics an AsyncSession whose flush failed: reads raise until rollback()."""

    def __init__(self) -> None:
        self.poisoned = False
        self.rollbacks = 0

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.poisoned = False


class PoisonAwareRepository(FakeDocumentRepositoryForFailure):
    def __init__(self, document: StubDocument, uow: PoisonedSessionUnitOfWork) -> None:
        super().__init__(document)
        self.uow = uow

    async def get(self, document_id: str):
        if self.uow.poisoned:
            raise RuntimeError("This Session's transaction has been rolled back")
        return self.document


class PoisoningStorage:
    """Fails like a flush rejected by Postgres: the session is left poisoned."""

    def __init__(self, uow: PoisonedSessionUnitOfWork) -> None:
        self.uow = uow

    def get_file(self, storage_path: str):
        self.uow.poisoned = True
        raise ValueError("storage is down")


@pytest.mark.asyncio
async def test_process_document_failure_rolls_back_before_recording_error():
    """A failed flush (e.g. NUL byte in chunk text) must not leave the doc stuck
    with a stale processing_attempt_id and an empty error_message."""
    document = StubDocument(
        id="doc_8",
        tenant_id="tenant-1",
        status=DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_8/file.txt",
        filename="file.txt",
        content_hash="hash-8",
        metadata_={},
    )
    uow = PoisonedSessionUnitOfWork()
    service = make_service(vector_store=FakeVectorStore(), neo4j_client=FakeNeo4jClient())
    service.document_repository = PoisonAwareRepository(document, uow)
    service.unit_of_work = uow
    service.storage = PoisoningStorage(uow)

    with pytest.raises(ValueError, match="storage is down"):
        await service.process_document("doc_8")

    assert uow.rollbacks >= 1
    assert document.status == DocumentStatus.FAILED
    assert document.error_message
    assert document.processing_attempt_id is None


class PdfStorage:
    def get_file(self, storage_path: str):
        return b"%PDF-1.7\n\x00binary"


class CapturingExtractor:
    def __init__(self) -> None:
        self.mime_type = None

    async def extract(self, file_content, mime_type, filename):
        self.mime_type = mime_type
        raise ValueError("stop after extraction")


@pytest.mark.asyncio
async def test_process_document_sniffs_pdf_stored_with_wrong_content_type():
    document = StubDocument(
        id="doc_9",
        tenant_id="tenant-1",
        status=DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_9/table.pdf",
        filename="table.pdf",
        content_hash="hash-9",
        metadata_={"content_type": "text/html"},
    )
    service = make_service(vector_store=FakeVectorStore(), neo4j_client=FakeNeo4jClient())
    service.document_repository = FakeDocumentRepositoryForFailure(document)
    service.unit_of_work = PoisonedSessionUnitOfWork()
    service.storage = PdfStorage()
    extractor = CapturingExtractor()
    service.content_extractor = extractor

    with pytest.raises(ValueError, match="stop after extraction"):
        await service.process_document("doc_9")

    assert extractor.mime_type == "application/pdf"


class NulExtractor:
    async def extract(self, file_content, mime_type, filename):
        from src.core.ingestion.infrastructure.extraction.base import ExtractionResult

        return ExtractionResult(content="a\x00b", extractor_used="stub", confidence=1.0)


@pytest.mark.asyncio
async def test_process_document_strips_nul_bytes_from_extracted_text(monkeypatch):
    seen = {}

    document = StubDocument(
        id="doc_10",
        tenant_id="tenant-1",
        status=DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_10/file.txt",
        filename="file.txt",
        content_hash="hash-10",
        metadata_={},
    )
    service = make_service(vector_store=FakeVectorStore(), neo4j_client=FakeNeo4jClient())
    service.document_repository = FakeDocumentRepositoryForFailure(document)
    service.unit_of_work = PoisonedSessionUnitOfWork()
    service.storage = PdfStorage()
    service.content_extractor = NulExtractor()

    from src.core.ingestion.infrastructure.extraction import config as extraction_config

    class _Settings:
        """Quality gate reads thresholds right after extraction; stop there."""

        def __getattr__(self, name):
            raise ValueError("stop after extraction")

    monkeypatch.setattr(extraction_config, "extraction_settings", _Settings())
    original_extract = service.content_extractor.extract

    async def capture(*args, **kwargs):
        result = await original_extract(*args, **kwargs)
        seen["result"] = result
        return result

    service.content_extractor.extract = capture

    with pytest.raises(ValueError, match="stop after extraction"):
        await service.process_document("doc_10")

    assert seen["result"].content == "ab"


class ExpiringUnitOfWork(PoisonedSessionUnitOfWork):
    """Like AsyncSession.rollback(): every loaded ORM object is expired, so
    reading any attribute afterwards needs IO (MissingGreenlet in async code)."""

    def __init__(self, repository: FakeDocumentRepositoryForFailure) -> None:
        super().__init__()
        self.repository = repository

    async def rollback(self) -> None:
        from sqlalchemy import inspect

        await super().rollback()
        generation = self.repository.generation
        if generation is not None:
            state = inspect(generation)
            state._expire(state.dict, set())


@pytest.mark.asyncio
async def test_process_document_failure_handler_does_not_read_expired_generation():
    document = StubDocument(
        id="doc_11",
        tenant_id="tenant-1",
        status=DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_11/file.txt",
        filename="file.txt",
        content_hash="hash-11",
        metadata_={},
    )
    repository = FakeDocumentRepositoryForFailure(document)
    uow = ExpiringUnitOfWork(repository)
    service = make_service(vector_store=FakeVectorStore(), neo4j_client=FakeNeo4jClient())
    service.document_repository = repository
    service.unit_of_work = uow
    service.storage = PoisoningStorage(uow)

    with pytest.raises(ValueError, match="storage is down"):
        await service.process_document("doc_11")

    assert uow.rollbacks >= 1
    assert document.status == DocumentStatus.FAILED
    assert document.error_message
    assert document.processing_attempt_id is None


class ExpiringPoisoningStorage(PoisoningStorage):
    """A failed flush can expire ORM state before the handler starts."""

    def __init__(self, uow, repository):
        super().__init__(uow)
        self.repository = repository

    def get_file(self, storage_path):
        from sqlalchemy import inspect

        generation = self.repository.generation
        self.generation_id = generation.id
        state = inspect(generation)
        state._expire(state.dict, set())
        return super().get_file(storage_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_generation", [False, True])
@pytest.mark.parametrize("preserve_published", [False, True])
async def test_failure_handler_handles_generation_already_expired_before_rollback(
    existing_generation, preserve_published,
):
    document = StubDocument(
        id="doc_expired_flush",
        tenant_id="tenant-1",
        status=DocumentStatus.READY if preserve_published else DocumentStatus.INGESTED,
        storage_path="tenant-1/doc_expired_flush/file.txt",
        filename="file.txt",
        content_hash="hash_expired_flush",
        metadata_={},
        active_generation_id="published_gen" if preserve_published else None,
    )
    repository = FakeDocumentRepositoryForFailure(document)
    if existing_generation:
        repository.generation = service_module.DocumentGeneration(
            id="gen_existing",
            document_id=document.id,
            tenant_id=document.tenant_id,
            filename=document.filename,
            content_hash=document.content_hash,
            storage_path=document.storage_path,
            metadata_={},
        )
        document.pending_generation_id = "gen_existing"

        async def delete_chunks(generation_id):
            return 0

        repository.delete_chunks_by_generation = delete_chunks

    failed_ids = []
    mark_failed = repository.mark_generation_failed

    async def record_failed(generation_id, error_message):
        failed_ids.append(generation_id)
        await mark_failed(generation_id, error_message)

    repository.mark_generation_failed = record_failed
    uow = ExpiringUnitOfWork(repository)
    service = make_service(vector_store=FakeVectorStore(), neo4j_client=FakeNeo4jClient())
    service.document_repository = repository
    service.unit_of_work = uow
    service.storage = ExpiringPoisoningStorage(uow, repository)

    with pytest.raises(ValueError, match="storage is down"):
        await service.process_document(document.id, force=preserve_published)

    assert uow.rollbacks >= 1
    assert repository.generation.status == "failed"
    assert repository.generation.error_message
    assert document.processing_attempt_id is None
    if preserve_published:
        assert document.status == DocumentStatus.READY
        assert document.active_generation_id == "published_gen"
        assert document.pending_generation_id is None
        assert service.vector_store.delete_calls == []
    else:
        assert document.status == DocumentStatus.FAILED
        assert document.error_message
    assert failed_ids == [service.storage.generation_id]
