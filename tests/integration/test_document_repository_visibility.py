import uuid

import pytest
from sqlalchemy import text

from src.core.database.session import configure_worker_session
from src.core.ingestion.domain.document import Document
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)


@pytest.fixture(autouse=True)
def _clear_visibility_cache():
    PostgresDocumentRepository.invalidate_visible_document_ids_cache()
    yield
    PostgresDocumentRepository.invalidate_visible_document_ids_cache()
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant


async def _ensure_tenant(session, tenant_id: str, name: str) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(Tenant(id=tenant_id, name=name))
        await session.flush()


async def _make_document(session, tenant_id: str, filename: str) -> Document:
    document = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        filename=filename,
        content_hash=str(uuid.uuid4()),
        storage_path=f"{tenant_id}/{filename}",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={"content_type": "text/markdown"},
    )
    session.add(document)
    await session.flush()
    return document


@pytest.mark.asyncio
async def test_list_visible_by_tenant_marks_local_docs(db_session, test_tenant_id):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    local_document = await _make_document(db_session, test_tenant_id, "engineering-notes.md")
    await db_session.commit()

    await db_session.execute(
        text("SELECT set_config('app.is_super_admin', 'false', false)")
    )
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": test_tenant_id},
    )

    repository = PostgresDocumentRepository(db_session)
    visible_documents = await repository.list_visible_by_tenant(test_tenant_id)

    assert len(visible_documents) == 1
    visible = visible_documents[0]
    assert visible.document.id == local_document.id
    assert visible.is_shared is False
    assert visible.owner_tenant_id == test_tenant_id
    assert visible.visible_from_tenant_id == test_tenant_id
    assert visible.share_mode is None


@pytest.mark.asyncio
async def test_get_visible_returns_shared_default_doc_for_target_tenant(db_session, test_tenant_id):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "System Default")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    shared_document = await _make_document(db_session, "default", "carbonio-ce-admin.md")
    await db_session.execute(
        text(
            """
            INSERT INTO document_shares (id, document_id, target_tenant_id, created_by, share_mode)
            VALUES (:id, :document_id, :target_tenant_id, :created_by, :share_mode)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "document_id": shared_document.id,
            "target_tenant_id": test_tenant_id,
            "created_by": "test-suite",
            "share_mode": "read",
        },
    )
    await db_session.commit()

    await db_session.execute(
        text("SELECT set_config('app.is_super_admin', 'false', false)")
    )
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": test_tenant_id},
    )

    repository = PostgresDocumentRepository(db_session)
    visible = await repository.get_visible(shared_document.id, test_tenant_id)

    assert visible is not None
    assert visible.document.id == shared_document.id
    assert visible.is_shared is True
    assert visible.owner_tenant_id == "default"
    assert visible.visible_from_tenant_id == test_tenant_id
    assert visible.share_mode == "read"



@pytest.mark.asyncio
async def test_list_visible_document_ids_splits_local_and_shared_default_visibility(
    db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "System Default")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")

    local_document = await _make_document(db_session, test_tenant_id, "engineering-notes.md")
    shared_default_document = await _make_document(db_session, "default", "carbonio-guide.md")
    unshared_default_document = await _make_document(db_session, "default", "private-admin.md")

    await db_session.execute(
        text(
            """
            INSERT INTO document_shares (id, document_id, target_tenant_id, created_by, share_mode)
            VALUES (:id, :document_id, :target_tenant_id, :created_by, :share_mode)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "document_id": shared_default_document.id,
            "target_tenant_id": test_tenant_id,
            "created_by": "test-suite",
            "share_mode": "read",
        },
    )
    await db_session.commit()

    await db_session.execute(
        text("SELECT set_config('app.is_super_admin', 'false', false)")
    )
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": test_tenant_id},
    )

    repository = PostgresDocumentRepository(db_session)

    local_ids = await repository.list_visible_document_ids(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
    )
    shared_default_ids = await repository.list_visible_document_ids(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id="default",
    )
    filtered_default_ids = await repository.list_visible_document_ids(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id="default",
        candidate_document_ids=[shared_default_document.id, unshared_default_document.id],
    )

    assert local_ids == [local_document.id]
    assert shared_default_ids == [shared_default_document.id]
    assert filtered_default_ids == [shared_default_document.id]


@pytest.mark.asyncio
async def test_list_visible_document_ids_uses_cache_until_invalidated(
    db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "System Default")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")

    shared_default_document = await _make_document(db_session, "default", "carbonio-cached-guide.md")
    share_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            """
            INSERT INTO document_shares (id, document_id, target_tenant_id, created_by, share_mode)
            VALUES (:id, :document_id, :target_tenant_id, :created_by, :share_mode)
            """
        ),
        {
            "id": share_id,
            "document_id": shared_default_document.id,
            "target_tenant_id": test_tenant_id,
            "created_by": "test-suite",
            "share_mode": "read",
        },
    )
    await db_session.commit()

    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": test_tenant_id},
    )

    repository = PostgresDocumentRepository(db_session)
    cached_ids = await repository.list_visible_document_ids(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id="default",
    )
    assert cached_ids == [shared_default_document.id]

    await configure_worker_session(db_session)
    await db_session.execute(
        text("DELETE FROM document_shares WHERE id = :share_id"),
        {"share_id": share_id},
    )
    await db_session.commit()

    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": test_tenant_id},
    )

    stale_ids = await repository.list_visible_document_ids(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id="default",
    )
    assert stale_ids == [shared_default_document.id]

    PostgresDocumentRepository.invalidate_visible_document_ids_cache(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id="default",
    )
    refreshed_ids = await repository.list_visible_document_ids(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id="default",
    )
    assert refreshed_ids == []
