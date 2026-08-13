import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document, DocumentGeneration
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.state.machine import DocumentStatus


@pytest.mark.asyncio
async def test_failed_generation_keeps_active_then_publish_switches_atomically():
    database_url = os.getenv("AMBER_MIRROR_DATABASE_URL")
    if not database_url:
        pytest.skip("AMBER_MIRROR_DATABASE_URL is not configured")

    engine = create_async_engine(database_url)
    marker = uuid4().hex[:12]
    document_id = f"doc_{marker}0000"
    old_id = f"old-{marker}"
    failed_id = f"failed-{marker}"
    new_id = f"new-{marker}"

    async with AsyncSession(engine, expire_on_commit=False) as session:
        repository = PostgresDocumentRepository(session)
        document = Document(
            id=document_id,
            tenant_id="generation-rehearsal",
            filename="old.txt",
            content_hash=f"old-hash-{marker}",
            storage_path=f"generation-rehearsal/{document_id}/old.txt",
            status=DocumentStatus.READY,
            metadata_={},
            keywords=[],
            hashtags=[],
            active_generation_id=old_id,
        )
        session.add(document)
        await session.flush()

        old = DocumentGeneration(
            id=old_id,
            document_id=document_id,
            tenant_id=document.tenant_id,
            filename=document.filename,
            content_hash=document.content_hash,
            storage_path=document.storage_path,
            status="published",
        )
        failed = DocumentGeneration(
            id=failed_id,
            document_id=document_id,
            tenant_id=document.tenant_id,
            filename="failed.txt",
            content_hash=f"failed-hash-{marker}",
            storage_path=f"generation-rehearsal/{document_id}/failed.txt",
        )
        await repository.save_generation(old)
        await repository.save_generation(failed)
        document.pending_generation_id = failed_id
        await repository.save(document)
        await repository.save_chunks(
            [
                Chunk(
                    id=f"chunk_{marker}0000_00000",
                    tenant_id=document.tenant_id,
                    document_id=document_id,
                    generation_id=old_id,
                    index=0,
                    content="old visible content",
                    tokens=3,
                    metadata_={},
                )
            ]
        )

        assert await repository.claim_processing_attempt(
            document_id, "attempt-failed", DocumentStatus.READY, failed_id
        )
        await repository.mark_generation_failed(failed_id, "synthetic failure")
        assert await repository.release_processing_attempt(document_id, "attempt-failed")
        document.pending_generation_id = None
        await repository.save(document)
        await session.flush()

        assert document.active_generation_id == old_id
        assert [
            chunk.content for chunk in await repository.get_chunks([f"chunk_{marker}0000_00000"])
        ] == ["old visible content"]

        new = DocumentGeneration(
            id=new_id,
            document_id=document_id,
            tenant_id=document.tenant_id,
            filename="new.txt",
            content_hash=f"new-hash-{marker}",
            storage_path=f"generation-rehearsal/{document_id}/new.txt",
        )
        await repository.save_generation(new)
        new_chunk_id = f"chunk_{marker}0000_00001"
        await repository.save_chunks(
            [
                Chunk(
                    id=new_chunk_id,
                    tenant_id=document.tenant_id,
                    document_id=document_id,
                    generation_id=new_id,
                    index=0,
                    content="new visible content",
                    tokens=3,
                    metadata_={},
                )
            ]
        )
        document.pending_generation_id = new_id
        await repository.save(document)
        assert await repository.claim_processing_attempt(
            document_id, "attempt-success", DocumentStatus.READY, new_id
        )
        assert await repository.publish_generation(document_id, new, "attempt-success")
        await session.flush()
        await session.refresh(document)

        assert document.active_generation_id == new_id
        assert [chunk.content for chunk in await repository.get_chunks([new_chunk_id])] == [
            "new visible content"
        ]
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DocumentGeneration)
                .where(DocumentGeneration.id == old_id)
            )
            == 1
        )

        await session.rollback()

    await engine.dispose()
