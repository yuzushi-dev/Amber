from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.cache import decorators as cache_decorators
from src.core.ingestion.application import ingestion_service as service_module
from src.core.ingestion.application.use_cases_documents import (
    UploadDocumentRequest,
    UploadDocumentUseCase,
)
from src.core.state.machine import DocumentStatus


class FakeRepo:
    def __init__(self) -> None:
        self.saved = []

    async def find_by_content_hash(self, *_args, **_kwargs):
        return None

    async def find_by_source_url(self, *_args, **_kwargs):
        return None

    async def find_by_filename(self, *_args, **_kwargs):
        return None

    async def save(self, document):
        self.saved.append(document)
        return document


class ExistingRepo(FakeRepo):
    def __init__(self, document, *, exact_match: bool) -> None:
        super().__init__()
        self.document = document
        self.exact_match = exact_match
        self.generations = []

    async def find_by_content_hash(self, *_args, **_kwargs):
        return self.document if self.exact_match else None

    async def find_by_filename(self, *_args, **_kwargs):
        return None if self.exact_match else self.document

    async def save_generation(self, generation):
        self.generations.append(generation)
        return generation


class FakeTaskDispatcher:
    def __init__(self) -> None:
        self.calls = []

    async def dispatch(self, task_name, args=None, kwargs=None):
        self.calls.append((task_name, args, kwargs))


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


def _stub_ingestion_components(monkeypatch):
    monkeypatch.setattr(service_module, "SemanticChunker", StubChunker)
    monkeypatch.setattr(service_module, "EmbeddingService", StubEmbeddingService)
    monkeypatch.setattr(service_module, "GraphProcessor", StubGraphProcessor)
    monkeypatch.setattr(service_module, "GraphEnricher", StubGraphEnricher)


def _existing_document(status: DocumentStatus):
    return SimpleNamespace(
        id="doc-existing",
        tenant_id="tenant",
        filename="file.txt",
        content_hash="old-hash",
        storage_path="tenant/doc-existing/file.txt",
        status=status,
        source_url=None,
        metadata_={},
        pending_generation_id=None,
        domain=None,
        summary=None,
        document_type=None,
        keywords=[],
        hashtags=[],
    )


def _upload_case(repo, dispatcher):
    return UploadDocumentUseCase(
        document_repository=repo,
        tenant_repository=repo,
        unit_of_work=FakeUoW(),
        storage=FakeStorage(),
        max_size_bytes=1024,
        graph_client=FakeGraphClient(),
        vector_store=None,
        task_dispatcher=dispatcher,
        event_dispatcher=None,
    )


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


@pytest.mark.asyncio
async def test_exact_reupload_retries_failed_document(monkeypatch):
    _stub_cache_delete(monkeypatch)
    _stub_ingestion_components(monkeypatch)
    repo = ExistingRepo(_existing_document(DocumentStatus.FAILED), exact_match=True)
    dispatcher = FakeTaskDispatcher()

    await _upload_case(repo, dispatcher).execute(
        UploadDocumentRequest("tenant", "file.txt", b"content", "text/plain")
    )

    assert dispatcher.calls == [
        ("src.workers.tasks.process_document", ["doc-existing", "tenant"], None)
    ]


@pytest.mark.asyncio
async def test_exact_reupload_does_not_reprocess_ready_document(monkeypatch):
    _stub_cache_delete(monkeypatch)
    _stub_ingestion_components(monkeypatch)
    repo = ExistingRepo(_existing_document(DocumentStatus.READY), exact_match=True)
    dispatcher = FakeTaskDispatcher()

    await _upload_case(repo, dispatcher).execute(
        UploadDocumentRequest("tenant", "file.txt", b"content", "text/plain")
    )

    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_changed_ready_document_dispatches_staged_generation(monkeypatch):
    _stub_cache_delete(monkeypatch)
    _stub_ingestion_components(monkeypatch)
    repo = ExistingRepo(_existing_document(DocumentStatus.READY), exact_match=False)
    dispatcher = FakeTaskDispatcher()

    await _upload_case(repo, dispatcher).execute(
        UploadDocumentRequest("tenant", "file.txt", b"changed", "text/plain")
    )

    assert repo.document.status == DocumentStatus.READY
    assert repo.document.pending_generation_id == repo.generations[0].id
    assert dispatcher.calls == [
        ("src.workers.tasks.process_document", ["doc-existing", "tenant"], None)
    ]


@pytest.mark.asyncio
async def test_concurrent_upload_integrity_error_falls_back_to_winner(monkeypatch):
    """Two concurrent uploads of identical content for the same tenant race
    past the check-then-act `find_by_content_hash` lookup. The DB-level
    `uq_documents_tenant_content_hash` constraint lets only one insert win;
    the loser must see a clean "deduplicated" result instead of an
    unhandled IntegrityError/500.
    """
    _stub_cache_delete(monkeypatch)
    _stub_ingestion_components(monkeypatch)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", _direct_to_thread)

    winner = _existing_document(DocumentStatus.INGESTED)

    class RaceRepo(FakeRepo):
        def __init__(self) -> None:
            super().__init__()
            self.lookup_calls = 0

        async def find_by_content_hash(self, *_args, **_kwargs):
            self.lookup_calls += 1
            # Call 1: UploadDocumentUseCase's own pre-insert check.
            # Call 2: IngestionService.register_document's internal dedup
            #         check. Both happen before either concurrent request
            #         has committed, so neither sees the winner yet.
            if self.lookup_calls <= 2:
                return None
            # Call 3: the post-rollback fallback lookup, after `save()`
            # below raises - by now the concurrent request has committed
            # the same (tenant_id, content_hash) row.
            return winner

        async def save(self, document):
            raise IntegrityError(
                "INSERT INTO documents ...",
                {},
                Exception(
                    "duplicate key value violates unique constraint "
                    '"uq_documents_tenant_content_hash"'
                ),
            )

    repo = RaceRepo()
    dispatcher = FakeTaskDispatcher()
    uow = FakeUoW()
    use_case = UploadDocumentUseCase(
        document_repository=repo,
        tenant_repository=repo,
        unit_of_work=uow,
        storage=FakeStorage(),
        max_size_bytes=1024,
        graph_client=FakeGraphClient(),
        vector_store=None,
        task_dispatcher=dispatcher,
        event_dispatcher=None,
    )

    result = await use_case.execute(
        UploadDocumentRequest("tenant", "file.txt", b"content", "text/plain")
    )

    assert repo.lookup_calls == 3
    assert result.document_id == winner.id
    assert result.is_duplicate is True
    # Winner is already INGESTED, so the loser must not re-dispatch processing.
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_concurrent_upload_integrity_error_reraises_when_no_winner_found(monkeypatch):
    """If the IntegrityError was not actually the content-hash race (e.g. the
    winning row is not yet visible, or it's a different constraint), the
    fallback lookup finds nothing and the original error must propagate
    rather than being silently swallowed.
    """
    _stub_cache_delete(monkeypatch)
    _stub_ingestion_components(monkeypatch)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", _direct_to_thread)

    class AlwaysFailRepo(FakeRepo):
        async def save(self, document):
            raise IntegrityError("INSERT INTO documents ...", {}, Exception("duplicate key"))

    repo = AlwaysFailRepo()
    use_case = UploadDocumentUseCase(
        document_repository=repo,
        tenant_repository=repo,
        unit_of_work=FakeUoW(),
        storage=FakeStorage(),
        max_size_bytes=1024,
        graph_client=FakeGraphClient(),
        vector_store=None,
        task_dispatcher=FakeTaskDispatcher(),
        event_dispatcher=None,
    )

    with pytest.raises(IntegrityError):
        await use_case.execute(
            UploadDocumentRequest("tenant", "file.txt", b"content", "text/plain")
        )
