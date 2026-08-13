from types import SimpleNamespace

import pytest

from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)


class _Result:
    def __init__(self, *, rowcount=0, rows=()):
        self.rowcount = rowcount
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []
        self.flushed = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
async def test_get_chunks_only_returns_the_document_active_or_legacy_generation():
    session = _Session([_Result(rows=[])])
    repository = PostgresDocumentRepository(session)

    await repository.get_chunks(["chunk-1"])

    sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN documents" in sql
    assert "documents.active_generation_id IS NULL" in sql
    assert "chunks.generation_id IS NULL" in sql
    assert "chunks.generation_id = documents.active_generation_id" in sql


@pytest.mark.asyncio
async def test_publish_generation_uses_pending_pointer_as_compare_and_set():
    session = _Session([_Result(rowcount=1), _Result(rowcount=1)])
    repository = PostgresDocumentRepository(session)
    generation = SimpleNamespace(
        id="gen-2",
        content_hash="hash-2",
        storage_path="tenant/doc/hash/file.pdf",
        filename="file.pdf",
        metadata_={},
        domain=None,
        summary=None,
        document_type=None,
        keywords=[],
        hashtags=[],
    )

    published = await repository.publish_generation("doc-1", generation, "attempt-1")

    assert published is True
    document_sql = str(session.statements[0])
    generation_sql = str(session.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "documents.pending_generation_id = :pending_generation_id_1" in document_sql
    assert "active_generation_id=:active_generation_id" in document_sql.replace(" ", "")
    assert "pending_generation_id=:pending_generation_id" in document_sql.replace(" ", "")
    assert "documents.processing_attempt_id = :processing_attempt_id_1" in document_sql
    assert "processing_attempt_id=:processing_attempt_id" in document_sql.replace(" ", "")
    assert "document_generations.status = 'staging'" in generation_sql
    assert "status='published'" in generation_sql.replace(" ", "")
    assert session.flushed == 1


@pytest.mark.asyncio
async def test_processing_attempt_claim_is_single_owner_compare_and_set():
    session = _Session([_Result(rowcount=1)])
    repository = PostgresDocumentRepository(session)

    claimed = await repository.claim_processing_attempt(
        "doc-1", "attempt-1", "ready", "gen-pending"
    )

    assert claimed is True
    compact = str(session.statements[0]).replace(" ", "")
    assert "documents.processing_attempt_idISNULL" in compact
    assert "documents.pending_generation_id=:pending_generation_id_1" in compact
    assert "documents.status=:status_1" in compact
    assert "processing_attempt_id=:processing_attempt_id" in compact


@pytest.mark.asyncio
async def test_attempt_owned_status_update_checks_owner_without_reassigning_it():
    session = _Session([_Result(rowcount=1)])
    repository = PostgresDocumentRepository(session)

    updated = await repository.update_status(
        "doc-1", "embedding", old_status="chunking", attempt_id="attempt-1"
    )

    assert updated is True
    compact = str(session.statements[0]).replace(" ", "")
    assert "documents.processing_attempt_id=:processing_attempt_id_1" in compact
    assert "SETstatus=:status" in compact
    assert "SETprocessing_attempt_id" not in compact


@pytest.mark.asyncio
async def test_processing_attempt_release_checks_owner():
    session = _Session([_Result(rowcount=1)])
    repository = PostgresDocumentRepository(session)

    released = await repository.release_processing_attempt("doc-1", "attempt-1")

    assert released is True
    compact = str(session.statements[0]).replace(" ", "")
    assert "documents.processing_attempt_id=:processing_attempt_id_1" in compact
    assert "SETprocessing_attempt_id=:processing_attempt_id" in compact
