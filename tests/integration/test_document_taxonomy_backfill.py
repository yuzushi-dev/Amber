"""
Integration tests for document taxonomy backfill script logic.

Tests the classify + update logic using the real DB session,
without invoking the CLI entrypoint.
"""
import uuid

import pytest

from src.core.ingestion.application.document_taxonomy import classify_document_taxonomy
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant


async def _ensure_tenant(session, tenant_id: str) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))
        await session.flush()


async def _make_folder(session, tenant_id: str, name: str) -> Folder:
    folder = Folder(
        id=str(uuid.uuid4()),
        name=name,
        tenant_id=tenant_id,
    )
    session.add(folder)
    await session.flush()
    return folder


async def _make_doc(session, tenant_id: str, filename: str, folder_id: str | None = None) -> Document:
    doc = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        filename=filename,
        content_hash=uuid.uuid4().hex,
        storage_path=f"{tenant_id}/test/{filename}",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={"content_type": "application/pdf"},
        folder_id=folder_id,
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest.mark.asyncio
async def test_backfill_admin_guide_folder(db_session, test_tenant_id):
    """Documents in AdminGuide folder get commercial/admin taxonomy."""
    from sqlalchemy import text, update
    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
    await _ensure_tenant(db_session, test_tenant_id)
    folder = await _make_folder(db_session, test_tenant_id, "AdminGuide")
    doc = await _make_doc(db_session, test_tenant_id, "admin-guide.pdf", folder.id)
    await db_session.commit()

    # Simulate backfill logic
    folder_map = {folder.id: folder.name}
    taxonomy = classify_document_taxonomy(
        folder_name=folder_map.get(doc.folder_id),
        document_title=doc.filename,
    )
    new_meta = dict(doc.metadata_ or {})
    new_meta["taxonomy"] = taxonomy
    await db_session.execute(
        update(Document).where(Document.id == doc.id).values(metadata_=new_meta)
    )
    await db_session.commit()

    await db_session.refresh(doc)
    assert doc.metadata_["taxonomy"]["edition"] == "commercial"
    assert doc.metadata_["taxonomy"]["audience"] == "admin"
    assert doc.metadata_["taxonomy"]["source_family"] == "admin_guide"


@pytest.mark.asyncio
async def test_backfill_ce_guide_folder(db_session, test_tenant_id):
    """Documents in CEGuide folder get ce/admin taxonomy."""
    from sqlalchemy import text, update
    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
    await _ensure_tenant(db_session, test_tenant_id)
    folder = await _make_folder(db_session, test_tenant_id, "CEGuide")
    doc = await _make_doc(db_session, test_tenant_id, "ce-guide.pdf", folder.id)
    await db_session.commit()

    taxonomy = classify_document_taxonomy(folder_name="CEGuide")
    new_meta = dict(doc.metadata_ or {})
    new_meta["taxonomy"] = taxonomy
    await db_session.execute(
        update(Document).where(Document.id == doc.id).values(metadata_=new_meta)
    )
    await db_session.commit()

    await db_session.refresh(doc)
    assert doc.metadata_["taxonomy"]["edition"] == "ce"
    assert doc.metadata_["taxonomy"]["source_family"] == "ce_guide"


@pytest.mark.asyncio
async def test_backfill_user_guide_folder(db_session, test_tenant_id):
    """Documents in UserGuide folder get commercial/user taxonomy."""
    from sqlalchemy import text, update
    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
    await _ensure_tenant(db_session, test_tenant_id)
    folder = await _make_folder(db_session, test_tenant_id, "UserGuide")
    doc = await _make_doc(db_session, test_tenant_id, "user-guide.pdf", folder.id)
    await db_session.commit()

    taxonomy = classify_document_taxonomy(folder_name="UserGuide")
    new_meta = dict(doc.metadata_ or {})
    new_meta["taxonomy"] = taxonomy
    await db_session.execute(
        update(Document).where(Document.id == doc.id).values(metadata_=new_meta)
    )
    await db_session.commit()

    await db_session.refresh(doc)
    assert doc.metadata_["taxonomy"]["audience"] == "user"
    assert doc.metadata_["taxonomy"]["source_family"] == "user_guide"


@pytest.mark.asyncio
async def test_backfill_zendesk_kb_with_admin_title(db_session, test_tenant_id):
    """ZendeskKB docs with admin keywords in filename get audience=admin."""
    from sqlalchemy import text, update
    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
    await _ensure_tenant(db_session, test_tenant_id)
    folder = await _make_folder(db_session, test_tenant_id, "ZendeskKB")
    doc = await _make_doc(db_session, test_tenant_id, "install-acme-mail-server.pdf", folder.id)
    await db_session.commit()

    taxonomy = classify_document_taxonomy(folder_name="ZendeskKB", document_title=doc.filename)
    new_meta = dict(doc.metadata_ or {})
    new_meta["taxonomy"] = taxonomy
    await db_session.execute(
        update(Document).where(Document.id == doc.id).values(metadata_=new_meta)
    )
    await db_session.commit()

    await db_session.refresh(doc)
    assert doc.metadata_["taxonomy"]["source_family"] == "zendesk_kb"
    assert doc.metadata_["taxonomy"]["audience"] == "admin"


@pytest.mark.asyncio
async def test_backfill_no_folder_yields_unknown(db_session, test_tenant_id):
    """Docs without a folder get unknown taxonomy and are not silently excluded."""
    from sqlalchemy import text, update
    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
    await _ensure_tenant(db_session, test_tenant_id)
    doc = await _make_doc(db_session, test_tenant_id, "misc-document.pdf", folder_id=None)
    await db_session.commit()

    taxonomy = classify_document_taxonomy(folder_name=None, document_title=doc.filename)
    new_meta = dict(doc.metadata_ or {})
    new_meta["taxonomy"] = taxonomy
    await db_session.execute(
        update(Document).where(Document.id == doc.id).values(metadata_=new_meta)
    )
    await db_session.commit()

    await db_session.refresh(doc)
    assert doc.metadata_["taxonomy"]["edition"] == "unknown"
    assert doc.metadata_["taxonomy"]["audience"] == "unknown"


@pytest.mark.asyncio
async def test_backfill_is_idempotent(db_session, test_tenant_id):
    """Running backfill twice on the same doc produces the same result."""
    from sqlalchemy import text, update
    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
    await _ensure_tenant(db_session, test_tenant_id)
    folder = await _make_folder(db_session, test_tenant_id, "AdminGuide")
    doc = await _make_doc(db_session, test_tenant_id, "admin-ref.pdf", folder.id)
    await db_session.commit()

    for _ in range(2):
        taxonomy = classify_document_taxonomy(folder_name="AdminGuide")
        new_meta = dict(doc.metadata_ or {})
        new_meta["taxonomy"] = taxonomy
        await db_session.execute(
            update(Document).where(Document.id == doc.id).values(metadata_=new_meta)
        )
        await db_session.commit()
        await db_session.refresh(doc)

    assert doc.metadata_["taxonomy"]["edition"] == "commercial"
    assert doc.metadata_["taxonomy"]["audience"] == "admin"
