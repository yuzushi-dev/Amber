"""
Regression tests for the FAILED/READY/NEEDS_REVIEW -> EXTRACTING retry paths
in IngestionService.process_document.

Bug: the CAS guard on the persisted status update was hardcoded to
`old_status=DocumentStatus.INGESTED`, regardless of which prior status
`TransitionManager.validate_transition` had just approved. The state
machine explicitly documents FAILED -> EXTRACTING ("Retry step"),
READY -> EXTRACTING ("Allow re-processing"), and NEEDS_REVIEW ->
EXTRACTING ("Retry/Force") as valid transitions, but the hardcoded CAS
meant every one of those retries passed validation and then silently
no-op'd, because the persisted row was never actually in the
'ingested' state. Found while retrying issue #106's no-graph-twin
documents in prod: two FAILED documents stayed FAILED across repeated
retry attempts with no error surfaced anywhere.
"""

import json

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
        self.error_message = None
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeDocumentRepository:
    """Mimics the real Postgres repository's atomic CAS semantics."""

    def __init__(self, document: StubDocument) -> None:
        self._document = document
        self.update_status_calls: list[tuple[str, str, str | None]] = []
        self.saved: list[StubDocument] = []

    async def get(self, document_id: str) -> StubDocument:
        return self._document

    async def update_status(self, document_id: str, status, old_status=None) -> bool:
        self.update_status_calls.append((document_id, status, old_status))
        if old_status is not None and self._document.status != old_status:
            return False
        self._document.status = status
        return True

    async def save(self, document: StubDocument) -> None:
        self.saved.append(document)


class FakeUnitOfWork:
    async def commit(self) -> None:
        pass


class ExplodingStorage:
    """Raises once process_document reaches the storage-read step, so the
    test only needs to exercise the transition guard, not the full
    extraction/chunking/embedding/graph pipeline."""

    def get_file(self, storage_path: str) -> bytes:
        raise RuntimeError("sentinel-stop-after-guard")


def make_service(document_repository, unit_of_work) -> service_module.IngestionService:
    return service_module.IngestionService(
        document_repository=document_repository,
        tenant_repository=None,
        unit_of_work=unit_of_work,
        storage_client=ExplodingStorage(),
        neo4j_client=object(),
        vector_store=None,
        settings=None,
        task_dispatcher=None,
        event_dispatcher=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prior_status",
    [
        DocumentStatus.INGESTED,
        DocumentStatus.FAILED,
        DocumentStatus.READY,
        DocumentStatus.NEEDS_REVIEW,
    ],
)
async def test_process_document_cas_uses_actual_prior_status(prior_status):
    document = StubDocument(
        id="doc_1",
        tenant_id="tenant-1",
        status=prior_status,
        storage_path="tenant-1/doc_1/file.txt",
        filename="file.txt",
        metadata_={},
    )
    repo = FakeDocumentRepository(document)
    service = make_service(repo, FakeUnitOfWork())

    with pytest.raises(RuntimeError, match="sentinel-stop-after-guard"):
        await service.process_document("doc_1")

    # The CAS must key off the status that was actually validated, not a
    # hardcoded INGESTED, otherwise retries from FAILED/READY/NEEDS_REVIEW
    # always silently no-op.
    assert repo.update_status_calls == [("doc_1", DocumentStatus.EXTRACTING, prior_status)]

    # Pipeline reached the storage step (guard did not block it) and the
    # error handler ran, persisting FAILED + a structured error message.
    assert repo.saved
    assert repo.saved[-1].status == DocumentStatus.FAILED
    error_data = json.loads(repo.saved[-1].error_message)
    assert "sentinel-stop-after-guard" in json.dumps(error_data)


@pytest.mark.asyncio
async def test_process_document_skips_invalid_prior_status_without_touching_db():
    # CHUNKING has no direct transition to EXTRACTING in the state machine.
    document = StubDocument(
        id="doc_2",
        tenant_id="tenant-1",
        status=DocumentStatus.CHUNKING,
        storage_path="tenant-1/doc_2/file.txt",
        filename="file.txt",
        metadata_={},
    )
    repo = FakeDocumentRepository(document)
    service = make_service(repo, FakeUnitOfWork())

    await service.process_document("doc_2")

    assert repo.update_status_calls == []
    assert repo.saved == []
    assert document.status == DocumentStatus.CHUNKING
