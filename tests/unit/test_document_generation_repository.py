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
    )

    published = await repository.publish_generation("doc-1", generation)

    assert published is True
    document_sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    generation_sql = str(session.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "documents.pending_generation_id = 'gen-2'" in document_sql
    assert "active_generation_id='gen-2'" in document_sql.replace(" ", "")
    assert "pending_generation_id=NULL" in document_sql.replace(" ", "")
    assert "document_generations.status = 'staging'" in generation_sql
    assert "status='published'" in generation_sql.replace(" ", "")
    assert session.flushed == 1
