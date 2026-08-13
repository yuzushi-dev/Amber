"""Unit tests for the two-level dedup / replace-in-place fix in
IngestionService.register_document.

Root cause under test: before this fix, register_document deduplicated only
on exact content_hash. Re-uploading updated content for an already-known
document (same filename, or same connector source_url) produced a brand new
document row with a brand new id (doc_id is derived from sha256(tenant_id +
content_hash)). Because document_shares.document_id and
group_document_access.document_id both carry ON DELETE CASCADE FKs, any
delete+create "fix" would silently drop shares/group grants already issued
for the old row. The correct fix reuses the existing row's id and updates it
in place.
"""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.core.ingestion.application import ingestion_service as service_module
from src.core.state.machine import DocumentStatus


class StubDocument:
    """Bypasses the real SQLAlchemy Document model; just an attribute bag."""

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


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


class FakeEventDispatcher:
    def __init__(self) -> None:
        self.events = []

    async def emit_state_change(self, event) -> None:
        self.events.append(event)


class FakeStorage:
    def __init__(self) -> None:
        self.upload_calls = []

    def upload_file(self, object_name, data, length, content_type) -> None:
        self.upload_calls.append((object_name, length, content_type))

    def get_file(self, path):
        return b"file-bytes-from-storage"


class InMemoryDocumentRepository:
    """Minimal in-memory stand-in with real query semantics (unlike a bare
    MagicMock) so "one row for this filename" / "shares survive" are
    genuinely checkable, not just assumed."""

    def __init__(self) -> None:
        self.rows: dict[str, StubDocument] = {}
        self.deleted_ids: list[str] = []
        # Simulate tables with ON DELETE CASCADE FKs on document_id.
        self.document_shares: dict[str, list[str]] = {}
        self.group_document_access: dict[str, list[str]] = {}

    def seed(self, document: StubDocument) -> None:
        self.rows[document.id] = document

    async def find_by_content_hash(self, tenant_id, content_hash):
        for doc in self.rows.values():
            if doc.tenant_id == tenant_id and doc.content_hash == content_hash:
                return doc
        return None

    async def find_by_source_url(self, tenant_id, source_url):
        if not source_url:
            return None
        candidates = [
            d for d in self.rows.values() if d.tenant_id == tenant_id and d.source_url == source_url
        ]
        candidates.sort(key=lambda d: d.created_at, reverse=True)
        return candidates[0] if candidates else None

    async def find_by_filename(self, tenant_id, filename):
        candidates = [
            d for d in self.rows.values() if d.tenant_id == tenant_id and d.filename == filename
        ]
        candidates.sort(key=lambda d: d.created_at, reverse=True)
        return candidates[0] if candidates else None

    async def save(self, document):
        self.rows[document.id] = document
        return document

    async def delete(self, document) -> None:
        # Mirrors ON DELETE CASCADE: deleting the document row also wipes
        # whatever "references" it via document_id.
        self.deleted_ids.append(document.id)
        self.rows.pop(document.id, None)
        self.document_shares.pop(document.id, None)
        self.group_document_access.pop(document.id, None)

    async def get_folder_name(self, folder_id):
        return None

    async def get(self, document_id):
        return self.rows.get(document_id)

    async def update_status(self, document_id, status, old_status=None, attempt_id=None) -> bool:
        doc = self.rows.get(document_id)
        if doc is None:
            return False
        doc.status = status
        if attempt_id is not None:
            doc.processing_attempt_id = attempt_id
        return True


def _patch_heavy_deps(monkeypatch) -> None:
    """Avoid constructing real SemanticChunker/EmbeddingService/etc in
    IngestionService.__init__ - same pattern as
    test_ingestion_service_event_dispatcher.py."""
    monkeypatch.setattr(service_module, "SemanticChunker", StubChunker)
    monkeypatch.setattr(service_module, "EmbeddingService", StubEmbeddingService)
    monkeypatch.setattr(service_module, "GraphProcessor", StubGraphProcessor)
    monkeypatch.setattr(service_module, "GraphEnricher", StubGraphEnricher)
    monkeypatch.setattr(service_module, "Document", StubDocument)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", _direct_to_thread)


def _build_service(
    repo: InMemoryDocumentRepository, storage: FakeStorage | None = None
) -> service_module.IngestionService:
    return service_module.IngestionService(
        document_repository=repo,
        tenant_repository=None,
        unit_of_work=None,
        storage_client=storage if storage is not None else FakeStorage(),
        neo4j_client=object(),
        vector_store=None,
        settings=None,
        task_dispatcher=None,
        event_dispatcher=FakeEventDispatcher(),
    )


def _existing_doc(**overrides) -> StubDocument:
    base = {
        "id": "doc_old0000000001",
        "tenant_id": "t1",
        "filename": "report.pdf",
        "content_hash": "hash_of_old_content",
        "storage_path": "t1/doc_old0000000001/report.pdf",
        "status": DocumentStatus.READY,
        "source_type": "file",
        "source_url": None,
        "metadata_": {"original_filename": "report.pdf", "content_type": "application/pdf"},
        "folder_id": None,
        "error_message": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "domain": None,
        "summary": "",
        "document_type": None,
        "hashtags": [],
        "keywords": [],
        "chunks": [],
    }
    base.update(overrides)
    return StubDocument(**base)


@pytest.mark.asyncio
async def test_register_document_replaces_on_filename_match_with_changed_content(monkeypatch):
    _patch_heavy_deps(monkeypatch)

    repo = InMemoryDocumentRepository()
    repo.seed(_existing_doc())

    service = _build_service(repo)

    new_content = b"UPDATED REPORT CONTENT " * 10
    new_doc = await service.register_document(
        tenant_id="t1",
        filename="report.pdf",
        file_content=new_content,
        content_type="application/pdf",
    )

    expected_hash = hashlib.sha256(new_content).hexdigest()

    assert new_doc.id == "doc_old0000000001", "the existing document's id must be preserved"
    assert new_doc.content_hash == expected_hash

    matching_rows = [
        d for d in repo.rows.values() if d.tenant_id == "t1" and d.filename == "report.pdf"
    ]
    assert len(matching_rows) == 1, "there must be exactly one row for this filename"


@pytest.mark.asyncio
async def test_register_document_preserves_shares_and_group_access_on_replace(monkeypatch):
    """Discriminates 'preserve id in place' from 'delete old row + create new
    row'. With delete+create, document_shares/group_document_access rows tied
    to the old id are cascade-deleted and this test fails."""
    _patch_heavy_deps(monkeypatch)

    repo = InMemoryDocumentRepository()
    repo.seed(_existing_doc(id="doc_shared0000001", filename="policy.pdf"))
    repo.document_shares["doc_shared0000001"] = ["share-A", "share-B"]
    repo.group_document_access["doc_shared0000001"] = ["group-X"]

    service = _build_service(repo)

    new_doc = await service.register_document(
        tenant_id="t1",
        filename="policy.pdf",
        file_content=b"UPDATED POLICY CONTENT",
        content_type="application/pdf",
    )

    assert repo.deleted_ids == [], "replace must not delete the existing document row"
    assert new_doc.id == "doc_shared0000001"
    assert repo.document_shares.get(new_doc.id) == ["share-A", "share-B"]
    assert repo.group_document_access.get(new_doc.id) == ["group-X"]


@pytest.mark.asyncio
async def test_register_document_source_url_takes_priority_over_filename(monkeypatch):
    _patch_heavy_deps(monkeypatch)

    # Scenario 1: same source_url, different filenames -> replace (one row).
    repo1 = InMemoryDocumentRepository()
    repo1.seed(
        _existing_doc(
            id="doc_url0000000001",
            filename="old_title.html",
            source_url="https://connector.example/item/42",
        )
    )
    service1 = _build_service(repo1)

    replaced = await service1.register_document(
        tenant_id="t1",
        filename="new_title.html",
        file_content=b"NEW CONTENT FOR SAME SOURCE",
        content_type="text/html",
        source_url="https://connector.example/item/42",
    )

    assert replaced.id == "doc_url0000000001"
    # filename must follow the new content: get_titles_by_ids() reads this column
    # to label sources, so a stale name would cite updated content wrongly.
    assert replaced.filename == "new_title.html"
    rows_for_source = [
        d
        for d in repo1.rows.values()
        if d.tenant_id == "t1" and d.source_url == "https://connector.example/item/42"
    ]
    assert len(rows_for_source) == 1

    # Scenario 2: same filename, different source_urls -> two distinct rows.
    repo2 = InMemoryDocumentRepository()
    repo2.seed(
        _existing_doc(
            id="doc_url0000000002",
            filename="doc_42.html",
            source_url="https://connector.example/item/42",
        )
    )
    service2 = _build_service(repo2)

    other = await service2.register_document(
        tenant_id="t1",
        filename="doc_42.html",
        file_content=b"CONTENT FOR A DIFFERENT SOURCE ITEM",
        content_type="text/html",
        source_url="https://connector.example/item/99",
    )

    assert other.id != "doc_url0000000002"
    rows_for_filename = [
        d for d in repo2.rows.values() if d.tenant_id == "t1" and d.filename == "doc_42.html"
    ]
    assert len(rows_for_filename) == 2, "different source_url must not be treated as a match"


class StubExtractor:
    async def extract(self, **kwargs):
        return SimpleNamespace(
            content="hello world " * 20,
            metadata={},
            extractor_used="text",
            confidence=1.0,
            extraction_time_ms=1,
        )


class StubClassifier:
    async def classify(self, content):
        return SimpleNamespace(value="general")

    async def close(self):
        return None


class StubStrategy:
    name = "stub"


class StubChunk:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class ThreeChunkChunker:
    """Stands in for SemanticChunker: always produces exactly 3 chunks,
    regardless of how many chunks the document had before reprocessing."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def chunk(self, content, document_title, metadata=None):
        return [
            SimpleNamespace(
                index=i, content=f"chunk-{i}", token_count=1, start_char=0, end_char=5, metadata={}
            )
            for i in range(3)
        ]


class _StopPipeline(Exception):
    pass


class RaisingVectorStoreFactory:
    def __call__(self, dimensions, collection_name=None):
        raise _StopPipeline("stop after chunking, before embedding")


@pytest.mark.asyncio
async def test_reprocess_replace_purges_stale_postgres_chunks(monkeypatch):
    """register_document (replace) + process_document: a document that had
    10 stale chunks ends up with exactly the 3 chunks produced from the new
    content - not 10 (stale never removed) and not 13 (appended instead of
    replaced)."""
    _patch_heavy_deps(monkeypatch)
    monkeypatch.setattr(
        "src.core.ingestion.application.chunking.semantic.SemanticChunker", ThreeChunkChunker
    )
    monkeypatch.setattr("src.core.ingestion.domain.chunk.Chunk", StubChunk)
    monkeypatch.setattr(
        "src.core.generation.application.intelligence.classifier.DomainClassifier", StubClassifier
    )
    monkeypatch.setattr(
        "src.core.generation.application.intelligence.strategies.get_strategy",
        lambda *_: StubStrategy(),
    )
    monkeypatch.setattr(
        "src.core.retrieval.application.embeddings_service.EmbeddingService", StubEmbeddingService
    )
    monkeypatch.setattr(
        "src.core.retrieval.application.sparse_embeddings_service.SparseEmbeddingService",
        StubEmbeddingService,
    )
    monkeypatch.setattr(
        "src.core.generation.domain.ports.provider_factory.build_provider_factory",
        lambda *a, **k: SimpleNamespace(get_embedding_provider=lambda *a, **k: None),
    )
    monkeypatch.setattr(
        "src.core.generation.domain.ports.provider_factory.get_provider_factory",
        lambda *a, **k: SimpleNamespace(get_embedding_provider=lambda *a, **k: None),
    )

    old_chunks = [StubChunk(id=f"chunk-old-{i}") for i in range(10)]
    existing = _existing_doc(
        id="doc_reprocess00001",
        content_hash="hash_of_old_content",
        chunks=old_chunks,
    )

    repo = InMemoryDocumentRepository()
    repo.seed(existing)

    class UnitOfWork:
        async def commit(self):
            return None

    class FakeTenantRepository:
        async def get(self, tenant_id):
            return SimpleNamespace(config={})

    service = service_module.IngestionService(
        document_repository=repo,
        tenant_repository=FakeTenantRepository(),
        unit_of_work=UnitOfWork(),
        storage_client=FakeStorage(),
        neo4j_client=object(),
        vector_store=None,
        content_extractor=StubExtractor(),
        settings=SimpleNamespace(
            default_embedding_provider="openai",
            default_embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            openai_api_key="sk-test",
            ollama_base_url=None,
        ),
        task_dispatcher=None,
        event_dispatcher=FakeEventDispatcher(),
        vector_store_factory=RaisingVectorStoreFactory(),
    )

    new_content = b"BRAND NEW SMALLER CONTENT " * 5
    replaced = await service.register_document(
        tenant_id="t1",
        filename="report.pdf",
        file_content=new_content,
        content_type="application/pdf",
    )
    assert replaced.id == "doc_reprocess00001"
    assert replaced is existing
    assert len(existing.chunks) == 10, "register_document itself must not touch chunks"

    with pytest.raises(_StopPipeline):
        await service.process_document("doc_reprocess00001")

    assert len(existing.chunks) == 3, (
        f"expected exactly 3 chunks after reprocess, got {len(existing.chunks)}"
    )
    new_chunk_ids = {c.id for c in existing.chunks}
    assert new_chunk_ids.isdisjoint({c.id for c in old_chunks}), (
        "old chunk rows must be replaced, not kept alongside the new ones"
    )


@pytest.mark.asyncio
async def test_replace_writes_a_new_object_key_instead_of_overwriting(monkeypatch):
    """A replace must never put_object over the key the old content lives under.

    The id is preserved by design, so `{tenant}/{id}/{filename}` is the *same*
    key whenever the filename is unchanged. StorageClient.upload_file is a plain
    put_object into a bucket created without versioning, so overwriting it
    destroys the original bytes irrecoverably — and process_document's pre-ingest
    cleanup then drops the old vectors and graph nodes, leaving nothing to
    recover from if the reprocess fails. provisioning_service also copies
    storage_path across tenants by reference, so the overwrite would mutate
    another tenant's document content too.

    Before the two-level dedup this was free: a content change minted a new
    doc_id, hence a new key.
    """
    _patch_heavy_deps(monkeypatch)

    repo = InMemoryDocumentRepository()
    existing = _existing_doc()
    repo.seed(existing)
    old_key = existing.storage_path

    storage = FakeStorage()
    service = _build_service(repo, storage=storage)

    new_content = b"UPDATED REPORT CONTENT " * 10
    new_doc = await service.register_document(
        tenant_id="t1",
        filename="report.pdf",  # unchanged: the colliding case
        file_content=new_content,
        content_type="application/pdf",
    )

    written_keys = [call[0] for call in storage.upload_calls]

    assert old_key not in written_keys, (
        f"replace wrote over the previous version's object ({old_key}); "
        "the original bytes are unrecoverable and a provisioned copy in another "
        "tenant would silently change content"
    )
    assert written_keys == [new_doc.storage_path]
    assert new_doc.storage_path != old_key
    # The key is derived from the new content, so any future re-replace also
    # lands somewhere new.
    assert hashlib.sha256(new_content).hexdigest()[:12] in new_doc.storage_path


@pytest.mark.asyncio
async def test_replace_invalidates_the_result_cache_immediately(monkeypatch):
    """A replace must drop the tenant's cached answers at replace time.

    The cache-hit path does not consult document status: _fetch_chunks_by_ids
    resolves chunk ids straight out of Postgres, so the non-READY blocklist that
    guards live vector/graph search does not apply to it. Chunk ids are
    deterministic and the document id is preserved, so entries cached before the
    replace still resolve - serving the OLD chunk text under the document's NEW
    filename.

    Invalidating only after a successful reprocess is not enough: that call sits
    inside process_document's try, so a failed reprocess leaves the stale entries
    alive until their TTL. This test fails if the invalidation moves back to the
    READY path only.
    """
    _patch_heavy_deps(monkeypatch)

    invalidated: list[str] = []

    class FakeResultCache:
        def __init__(self, _config) -> None:
            pass

        async def invalidate_tenant(self, tenant_id: str) -> None:
            invalidated.append(tenant_id)

    import src.core.cache.result_cache as rc_module
    import src.shared.kernel.runtime as runtime_module

    monkeypatch.setattr(rc_module, "ResultCache", FakeResultCache)
    monkeypatch.setattr(rc_module, "ResultCacheConfig", lambda **kw: object())
    # Patch the accessor, NOT configure_settings(): calling that in a test leaks
    # global state and has already masked a real RuntimeError in this suite once.
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: SimpleNamespace(db=SimpleNamespace(redis_url="redis://stub:6379/0")),
    )

    repo = InMemoryDocumentRepository()
    repo.seed(_existing_doc())
    service = _build_service(repo)

    await service.register_document(
        tenant_id="t1",
        filename="report.pdf",
        file_content=b"UPDATED REPORT CONTENT for the cache test",
        content_type="application/pdf",
    )

    assert invalidated == ["t1"], (
        "replace must invalidate the tenant result cache before the reprocess, "
        "otherwise a cache hit serves pre-replace chunk text under the new filename"
    )


@pytest.mark.asyncio
async def test_exact_content_match_does_not_invalidate_the_cache(monkeypatch):
    """Discriminates 'invalidate on replace' from 'invalidate on every upload'.

    An exact content_hash match returns the existing document untouched, so the
    cached answers are still correct and dropping them would throw away a warm
    cache on every duplicate re-upload.
    """
    _patch_heavy_deps(monkeypatch)

    invalidated: list[str] = []

    class FakeResultCache:
        def __init__(self, _config) -> None:
            pass

        async def invalidate_tenant(self, tenant_id: str) -> None:
            invalidated.append(tenant_id)

    import src.core.cache.result_cache as rc_module
    import src.shared.kernel.runtime as runtime_module

    monkeypatch.setattr(rc_module, "ResultCache", FakeResultCache)
    monkeypatch.setattr(rc_module, "ResultCacheConfig", lambda **kw: object())
    # Patch the accessor, NOT configure_settings(): calling that in a test leaks
    # global state and has already masked a real RuntimeError in this suite once.
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: SimpleNamespace(db=SimpleNamespace(redis_url="redis://stub:6379/0")),
    )

    same_content = b"IDENTICAL CONTENT"
    repo = InMemoryDocumentRepository()
    repo.seed(_existing_doc(content_hash=hashlib.sha256(same_content).hexdigest()))
    service = _build_service(repo)

    await service.register_document(
        tenant_id="t1",
        filename="report.pdf",
        file_content=same_content,
        content_type="application/pdf",
    )

    assert invalidated == [], "an exact-hash dedup must not drop the tenant's warm cache"
