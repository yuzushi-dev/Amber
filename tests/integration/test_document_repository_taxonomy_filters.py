"""
Integration tests for taxonomy-aware document visibility filtering.
"""
import uuid

import pytest
from sqlalchemy import text

from src.core.database.session import configure_worker_session
from src.core.ingestion.domain.document import Document
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant


@pytest.fixture(autouse=True)
def _clear_visibility_cache():
    PostgresDocumentRepository.invalidate_visible_document_ids_cache()
    yield
    PostgresDocumentRepository.invalidate_visible_document_ids_cache()


async def _ensure_tenant(session, tenant_id: str) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))
        await session.flush()


async def _make_doc(session, tenant_id: str, edition: str, audience: str, source_family: str) -> Document:
    doc = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        filename=f"{edition}-{audience}-{uuid.uuid4().hex[:6]}.md",
        content_hash=uuid.uuid4().hex,
        storage_path=f"{tenant_id}/test/file.md",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={
            "content_type": "text/markdown",
            "taxonomy": {
                "product_line": "acme-mail",
                "edition": edition,
                "audience": audience,
                "source_family": source_family,
            },
        },
    )
    session.add(doc)
    await session.flush()
    return doc


async def _configure_session(session, tenant_id: str):
    await configure_worker_session(session)
    await session.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    await session.execute(
        text("SELECT set_config('app.current_tenant', :t, false)"),
        {"t": tenant_id},
    )


@pytest.mark.asyncio
async def test_edition_filter_excludes_wrong_edition(db_session, test_tenant_id):
    """edition=commercial should exclude ce docs."""
    await _ensure_tenant(db_session, test_tenant_id)
    commercial_doc = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    ce_doc = await _make_doc(db_session, test_tenant_id, "ce", "admin", "ce_guide")
    await db_session.commit()
    await _configure_session(db_session, test_tenant_id)

    repo = PostgresDocumentRepository(db_session)
    result = await repo.list_visible_document_ids_by_taxonomy(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
        edition="commercial",
    )

    assert commercial_doc.id in result
    assert ce_doc.id not in result


@pytest.mark.asyncio
async def test_audience_filter_excludes_wrong_audience(db_session, test_tenant_id):
    """audience=admin should exclude user docs."""
    await _ensure_tenant(db_session, test_tenant_id)
    admin_doc = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    user_doc = await _make_doc(db_session, test_tenant_id, "commercial", "user", "user_guide")
    await db_session.commit()
    await _configure_session(db_session, test_tenant_id)

    repo = PostgresDocumentRepository(db_session)
    result = await repo.list_visible_document_ids_by_taxonomy(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
        audience="admin",
    )

    assert admin_doc.id in result
    assert user_doc.id not in result


@pytest.mark.asyncio
async def test_combined_edition_and_audience_filter(db_session, test_tenant_id):
    """edition=commercial AND audience=admin excludes other combinations."""
    await _ensure_tenant(db_session, test_tenant_id)
    target = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    ce_admin = await _make_doc(db_session, test_tenant_id, "ce", "admin", "ce_guide")
    comm_user = await _make_doc(db_session, test_tenant_id, "commercial", "user", "user_guide")
    await db_session.commit()
    await _configure_session(db_session, test_tenant_id)

    repo = PostgresDocumentRepository(db_session)
    result = await repo.list_visible_document_ids_by_taxonomy(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
        edition="commercial",
        audience="admin",
    )

    assert target.id in result
    assert ce_admin.id not in result
    assert comm_user.id not in result


@pytest.mark.asyncio
async def test_unknown_docs_excluded_when_edition_filter_set(db_session, test_tenant_id):
    """unknown edition docs are excluded when an explicit edition filter is active."""
    await _ensure_tenant(db_session, test_tenant_id)
    known_doc = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    unknown_doc = await _make_doc(db_session, test_tenant_id, "unknown", "unknown", "unknown")
    await db_session.commit()
    await _configure_session(db_session, test_tenant_id)

    repo = PostgresDocumentRepository(db_session)
    result = await repo.list_visible_document_ids_by_taxonomy(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
        edition="commercial",
    )

    assert known_doc.id in result
    assert unknown_doc.id not in result


@pytest.mark.asyncio
async def test_unknown_docs_survive_when_no_filter(db_session, test_tenant_id):
    """Without any taxonomy filter, all docs (including unknown) are returned."""
    await _ensure_tenant(db_session, test_tenant_id)
    known_doc = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    unknown_doc = await _make_doc(db_session, test_tenant_id, "unknown", "unknown", "unknown")
    await db_session.commit()
    await _configure_session(db_session, test_tenant_id)

    repo = PostgresDocumentRepository(db_session)
    result = await repo.list_visible_document_ids_by_taxonomy(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
    )

    assert known_doc.id in result
    assert unknown_doc.id in result


@pytest.mark.asyncio
async def test_candidate_document_ids_are_intersected(db_session, test_tenant_id):
    """candidate_document_ids further restricts the taxonomy-filtered set."""
    await _ensure_tenant(db_session, test_tenant_id)
    doc_a = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    doc_b = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    await db_session.commit()
    await _configure_session(db_session, test_tenant_id)

    repo = PostgresDocumentRepository(db_session)
    result = await repo.list_visible_document_ids_by_taxonomy(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
        candidate_document_ids=[doc_a.id],
        edition="commercial",
    )

    assert doc_a.id in result
    assert doc_b.id not in result


@pytest.mark.asyncio
async def test_source_family_filter(db_session, test_tenant_id):
    """source_family filter works independently."""
    await _ensure_tenant(db_session, test_tenant_id)
    kb_doc = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "zendesk_kb")
    guide_doc = await _make_doc(db_session, test_tenant_id, "commercial", "admin", "admin_guide")
    await db_session.commit()
    await _configure_session(db_session, test_tenant_id)

    repo = PostgresDocumentRepository(db_session)
    result = await repo.list_visible_document_ids_by_taxonomy(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id=test_tenant_id,
        source_family="zendesk_kb",
    )

    assert kb_doc.id in result
    assert guide_doc.id not in result
