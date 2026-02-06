import pytest

from src.core.cache import decorators as cache_decorators
from src.core.ingestion.application import ingestion_service as service_module
from src.core.ingestion.application.use_cases_documents import (
    UploadDocumentRequest,
    UploadDocumentUseCase,
)


class FakeRepo:
    def __init__(self) -> None:
        self.saved = []

    async def find_by_content_hash(self, *_args, **_kwargs):
        return None

    async def save(self, document):
        self.saved.append(document)
        return document


class FakeUoW:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class FakeStorage:
    def upload_file(self, *_args, **_kwargs):
        return None


class FakeGraphClient:
    async def execute_write(self, *_args, **_kwargs):
        return None

    async def execute_read(self, *_args, **_kwargs):
        return []


class StubChunker:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubEmbeddingService:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubGraphProcessor:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubGraphEnricher:
    def __init__(self, *args, **kwargs) -> None:
        pass


class StubDocument:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def _stub_cache_delete(monkeypatch):
    async def _delete_cache(_key: str):
        return True

    monkeypatch.setattr(cache_decorators, "delete_cache", _delete_cache)


@pytest.mark.asyncio
async def test_upload_use_case_accepts_ports_only(monkeypatch):
    monkeypatch.setattr(service_module, "SemanticChunker", StubChunker)
    monkeypatch.setattr(service_module, "EmbeddingService", StubEmbeddingService)
    monkeypatch.setattr(service_module, "GraphProcessor", StubGraphProcessor)
    monkeypatch.setattr(service_module, "GraphEnricher", StubGraphEnricher)
    monkeypatch.setattr(service_module, "Document", StubDocument)
    _stub_cache_delete(monkeypatch)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", _direct_to_thread)

    uow = FakeUoW()
    use_case = UploadDocumentUseCase(
        document_repository=FakeRepo(),
        tenant_repository=FakeRepo(),
        unit_of_work=uow,
        storage=FakeStorage(),
        max_size_bytes=1024,
        graph_client=FakeGraphClient(),
        vector_store=None,
        task_dispatcher=None,
        event_dispatcher=None,
    )

    result = await use_case.execute(
        UploadDocumentRequest(
            tenant_id="tenant",
            filename="file.txt",
            content=b"hello",
            content_type="text/plain",
        )
    )

    assert result.document_id
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_upload_use_case_invalidates_tenant_stats_cache(monkeypatch):
    monkeypatch.setattr(service_module, "SemanticChunker", StubChunker)
    monkeypatch.setattr(service_module, "EmbeddingService", StubEmbeddingService)
    monkeypatch.setattr(service_module, "GraphProcessor", StubGraphProcessor)
    monkeypatch.setattr(service_module, "GraphEnricher", StubGraphEnricher)
    monkeypatch.setattr(service_module, "Document", StubDocument)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", _direct_to_thread)

    deleted_keys: list[str] = []

    async def _delete_cache(key: str):
        deleted_keys.append(key)

    monkeypatch.setattr(cache_decorators, "delete_cache", _delete_cache)

    uow = FakeUoW()
    use_case = UploadDocumentUseCase(
        document_repository=FakeRepo(),
        tenant_repository=FakeRepo(),
        unit_of_work=uow,
        storage=FakeStorage(),
        max_size_bytes=1024,
        graph_client=FakeGraphClient(),
        vector_store=None,
        task_dispatcher=None,
        event_dispatcher=None,
    )

    result = await use_case.execute(
        UploadDocumentRequest(
            tenant_id="tenant-cache",
            filename="cache.txt",
            content=b"hello",
            content_type="text/plain",
        )
    )

    assert result.status == "ingested"
    assert deleted_keys == [
        "admin:stats:database:tenant-cache",
        "admin:stats:vectors:tenant-cache",
    ]
