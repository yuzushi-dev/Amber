import hashlib
import inspect
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.core.ingestion.application import ingestion_service as service_module
from src.core.state.machine import DocumentStatus


class _Noop:
    def __init__(self, *args, **kwargs):
        pass


class _Repo:
    def __init__(self, document):
        self.document = document
        self.generations = []

    async def find_by_content_hash(self, tenant_id, content_hash):
        return None

    async def find_by_source_url(self, tenant_id, source_url):
        return None

    async def find_by_filename(self, tenant_id, filename):
        return self.document

    async def save(self, document):
        self.document = document
        return document

    async def save_generation(self, generation):
        self.generations.append(generation)
        return generation


class _Storage:
    def upload_file(self, **_kwargs):
        pass


@pytest.fixture(autouse=True)
def _lightweight_service(monkeypatch):
    monkeypatch.setattr(service_module, "SemanticChunker", _Noop)
    monkeypatch.setattr(service_module, "EmbeddingService", _Noop)
    monkeypatch.setattr(service_module, "GraphProcessor", _Noop)
    monkeypatch.setattr(service_module, "GraphEnricher", _Noop)

    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", direct)


@pytest.mark.asyncio
async def test_replace_stages_new_content_without_changing_published_document():
    document = SimpleNamespace(
        id="doc_0123456789abcdef",
        tenant_id="tenant-1",
        filename="published.pdf",
        content_hash="published-hash",
        storage_path="tenant-1/doc/published.pdf",
        status=DocumentStatus.READY,
        source_url=None,
        metadata_={"published": True},
        pending_generation_id=None,
        created_at=datetime.now(UTC),
    )
    repository = _Repo(document)
    service = service_module.IngestionService(
        document_repository=repository,
        tenant_repository=None,
        unit_of_work=None,
        storage_client=_Storage(),
        neo4j_client=object(),
        vector_store=None,
    )
    replacement = b"new content"

    result = await service.register_document(
        tenant_id="tenant-1",
        filename="replacement.pdf",
        file_content=replacement,
        content_type="application/pdf",
    )

    assert result is document
    assert document.filename == "published.pdf"
    assert document.content_hash == "published-hash"
    assert document.storage_path == "tenant-1/doc/published.pdf"
    assert document.status == DocumentStatus.READY
    assert document.pending_generation_id == repository.generations[0].id
    assert repository.generations[0].filename == "replacement.pdf"
    assert repository.generations[0].content_hash == hashlib.sha256(replacement).hexdigest()


def test_process_document_never_performs_document_wide_predelete():
    source = inspect.getsource(service_module.IngestionService.process_document)

    assert ".delete_by_document(" not in source
    assert "DETACH DELETE c" not in source


@pytest.mark.asyncio
async def test_duplicate_worker_stops_before_reading_staging_generation():
    document = SimpleNamespace(
        id="doc_0123456789abcdef",
        tenant_id="tenant-1",
        filename="published.pdf",
        content_hash="published-hash",
        storage_path="tenant-1/doc/published.pdf",
        status=DocumentStatus.READY,
        pending_generation_id="gen-pending",
        processing_attempt_id=None,
        metadata_={},
    )

    class _ClaimRejectedRepo:
        def __init__(self):
            self.claims = []

        async def get(self, _document_id):
            return document

        async def claim_processing_attempt(self, *args):
            self.claims.append(args)
            return False

        async def get_generation(self, _generation_id):
            raise AssertionError("losing worker must not read staging artifacts")

    repository = _ClaimRejectedRepo()
    service = service_module.IngestionService(
        document_repository=repository,
        tenant_repository=None,
        unit_of_work=SimpleNamespace(commit=lambda: None),
        storage_client=object(),
        neo4j_client=object(),
        vector_store=None,
    )

    await service.process_document(document.id)

    assert len(repository.claims) == 1
