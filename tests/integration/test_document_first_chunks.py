import uuid

import pytest
from sqlalchemy import text

from src.core.database.session import configure_worker_session
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document, DocumentGeneration
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant

pytestmark = pytest.mark.integration


async def _document(session, tenant_id, name):
    document = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        filename=name,
        content_hash=str(uuid.uuid4()),
        storage_path=f"{tenant_id}/{name}",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={"content_type": "text/markdown"},
    )
    session.add(document)
    await session.flush()
    return document


def _chunk(document, index, generation_id=None):
    return Chunk(
        id=str(uuid.uuid4()),
        tenant_id=document.tenant_id,
        document_id=document.id,
        generation_id=generation_id,
        index=index,
        content=f"{document.filename} #{index} gen={generation_id}",
        tokens=3,
    )


@pytest.mark.asyncio
async def test_get_first_chunks_serves_only_the_published_generation(db_session, test_tenant_id):
    await configure_worker_session(db_session)
    if await db_session.get(Tenant, test_tenant_id) is None:
        db_session.add(Tenant(id=test_tenant_id, name="Integration Test Tenant"))
        await db_session.flush()

    # Document with an active generation: a legacy NULL-generation idx 0 must be ignored.
    versioned = await _document(db_session, test_tenant_id, "versioned.md")
    generation = DocumentGeneration(
        id=str(uuid.uuid4()),
        document_id=versioned.id,
        tenant_id=test_tenant_id,
        content_hash=versioned.content_hash,
        storage_path=versioned.storage_path,
        filename=versioned.filename,
        status="published",
    )
    db_session.add(generation)
    await db_session.flush()
    versioned.active_generation_id = generation.id
    legacy = _chunk(versioned, 0, None)
    active_first = _chunk(versioned, 1, generation.id)
    active_second = _chunk(versioned, 2, generation.id)

    # Document without any generation: its NULL-generation idx 0 is served.
    legacy_only = await _document(db_session, test_tenant_id, "legacy.md")
    legacy_head = _chunk(legacy_only, 0, None)
    legacy_tail = _chunk(legacy_only, 1, None)

    db_session.add_all([legacy, active_first, active_second, legacy_head, legacy_tail])
    await db_session.commit()

    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": test_tenant_id},
    )

    heads = await PostgresDocumentRepository(db_session).get_first_chunks(
        [versioned.id, legacy_only.id]
    )

    assert heads[versioned.id].id == active_first.id
    assert heads[legacy_only.id].id == legacy_head.id
    assert len(heads) == 2
