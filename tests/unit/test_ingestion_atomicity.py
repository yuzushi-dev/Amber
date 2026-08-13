from types import SimpleNamespace

import pytest

from src.core.ingestion.application import ingestion_service as service_module
from src.core.ingestion.application.use_cases_documents import (
    UploadDocumentRequest,
    UploadDocumentUseCase,
)
from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus


class _Noop:
    def __init__(self, *args, **kwargs):
        pass


class _Repo:
    def __init__(self, save_error=None):
        self.document = None
        self.save_error = save_error

    async def find_by_content_hash(self, _tenant_id, _content_hash):
        return None

    async def find_by_source_url(self, _tenant_id, _source_url):
        return None

    async def find_by_filename(self, _tenant_id, _filename):
        return None

    async def get_folder_name(self, _folder_id):
        return None

    async def save(self, document):
        if self.save_error:
            raise self.save_error
        self.document = document
        return document

    async def update_status(self, _document_id, status, old_status=None, attempt_id=None):
        self.document.status = status
        if attempt_id is not None:
            self.document.processing_attempt_id = attempt_id
        return True


class _Storage:
    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def upload_file(self, object_name, data, length, content_type):
        self.uploaded.append(object_name)

    def delete_file(self, object_name):
        self.deleted.append(object_name)


class _Uow:
    def __init__(self, commit_error=None):
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    async def rollback(self):
        self.rollbacks += 1


class _FailingDispatcher:
    async def dispatch(self, *_args, **_kwargs):
        raise RuntimeError("broker unavailable")


@pytest.fixture(autouse=True)
def _stub_ingestion_dependencies(monkeypatch):
    monkeypatch.setattr(service_module, "SemanticChunker", _Noop)
    monkeypatch.setattr(service_module, "EmbeddingService", _Noop)
    monkeypatch.setattr(service_module, "GraphProcessor", _Noop)
    monkeypatch.setattr(service_module, "GraphEnricher", _Noop)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", _direct_to_thread)


@pytest.mark.asyncio
async def test_registration_failure_removes_uploaded_object(monkeypatch):
    monkeypatch.setattr(service_module, "Document", SimpleNamespace)
    repo = _Repo(save_error=RuntimeError("database unavailable"))
    storage = _Storage()
    service = service_module.IngestionService(
        document_repository=repo,
        tenant_repository=None,
        unit_of_work=_Uow(),
        storage_client=storage,
        neo4j_client=object(),
        vector_store=None,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.register_document("tenant-1", "file.txt", b"hello", "text/plain")

    assert storage.deleted == storage.uploaded


@pytest.mark.asyncio
async def test_dispatch_failure_is_persisted_as_retryable_failed_document(monkeypatch):
    from src.core.cache import decorators as cache_decorators

    monkeypatch.setattr(service_module, "Document", SimpleNamespace)

    async def _delete_cache(_key):
        return None

    monkeypatch.setattr(cache_decorators, "delete_cache", _delete_cache)
    repo = _Repo()
    storage = _Storage()
    use_case = UploadDocumentUseCase(
        document_repository=repo,
        tenant_repository=None,
        unit_of_work=_Uow(),
        storage=storage,
        max_size_bytes=1024,
        graph_client=object(),
        vector_store=None,
        task_dispatcher=_FailingDispatcher(),
    )

    result = await use_case.execute(
        UploadDocumentRequest(
            tenant_id="tenant-1",
            filename="file.txt",
            content=b"hello",
            content_type="text/plain",
        )
    )

    assert result.action == "dispatch_failed"
    assert repo.document.status == DocumentStatus.FAILED
    assert "broker unavailable" in repo.document.error_message


def test_document_content_hash_is_unique_per_tenant():
    constraints = {constraint.name for constraint in Document.__table__.constraints}
    assert "uq_documents_tenant_content_hash" in constraints
