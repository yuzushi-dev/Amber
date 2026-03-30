import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
from src.core.admin_ops.domain.audit import AuditLog
from src.core.database.session import configure_worker_session
from src.core.ingestion.application.document_sharing_service import DocumentSharingService
from src.core.ingestion.domain.document import Document
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant
from src.shared.security import generate_api_key, hash_api_key

TEST_DOC_PREFIX = "share-management-"
TEST_KEY_NAME_PREFIX = "Share Management Test"
EXTRA_TENANT_ID = "share-target-beta"


@pytest.fixture(autouse=True)
def _fail_open_rate_limit(monkeypatch):
    import src.api.middleware.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module.settings.rate_limits, "fail_open", True)
    rate_limit_module._rate_limiter = None


@pytest_asyncio.fixture(autouse=True)
async def cleanup_share_management_artifacts(db_session: AsyncSession):
    await configure_worker_session(db_session)

    PostgresDocumentRepository.invalidate_visible_document_ids_cache()

    async def _wipe():
        await db_session.execute(
            delete(AuditLog).where(AuditLog.action.like("document_share%"))
        )
        await db_session.execute(
            text(
                "DELETE FROM document_shares WHERE document_id IN ("
                "SELECT id FROM documents WHERE filename LIKE :prefix)"
            ),
            {"prefix": f"{TEST_DOC_PREFIX}%"},
        )
        await db_session.execute(
            text("DELETE FROM documents WHERE filename LIKE :prefix"),
            {"prefix": f"{TEST_DOC_PREFIX}%"},
        )
        await db_session.execute(
            text(
                "DELETE FROM api_key_tenants WHERE api_key_id IN ("
                "SELECT id FROM api_keys WHERE name LIKE :prefix)"
            ),
            {"prefix": f"{TEST_KEY_NAME_PREFIX}%"},
        )
        await db_session.execute(
            text("DELETE FROM api_keys WHERE name LIKE :prefix"),
            {"prefix": f"{TEST_KEY_NAME_PREFIX}%"},
        )
        await db_session.execute(
            text("DELETE FROM tenants WHERE id = :tenant_id"),
            {"tenant_id": EXTRA_TENANT_ID},
        )
        await db_session.commit()

    await _wipe()
    yield
    await _wipe()
    PostgresDocumentRepository.invalidate_visible_document_ids_cache()


async def _ensure_tenant(session: AsyncSession, tenant_id: str, name: str) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(Tenant(id=tenant_id, name=name))
        await session.flush()


async def _seed_default_document(session: AsyncSession) -> Document:
    document = Document(
        id=str(uuid.uuid4()),
        tenant_id="default",
        filename=f"{TEST_DOC_PREFIX}{uuid.uuid4()}.md",
        content_hash=str(uuid.uuid4()),
        storage_path=f"default/{uuid.uuid4()}.md",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={"content_type": "text/markdown"},
    )
    session.add(document)
    await session.flush()
    return document


@pytest_asyncio.fixture
async def default_admin_api_key(db_session: AsyncSession) -> str:
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "Global Admin")

    raw_key = generate_api_key(prefix="test")
    key_record = ApiKey(
        name=f"{TEST_KEY_NAME_PREFIX} Default Admin {uuid.uuid4()}",
        prefix="test",
        hashed_key=hash_api_key(raw_key),
        last_chars=raw_key[-4:],
        is_active=True,
        scopes=["admin", "read", "write"],
    )
    db_session.add(key_record)
    await db_session.flush()
    db_session.add(
        ApiKeyTenant(api_key_id=key_record.id, tenant_id="default", role="admin")
    )
    await db_session.commit()
    return raw_key


@pytest.mark.asyncio
async def test_default_admin_can_list_and_add_document_shares(
    client, db_session, default_admin_api_key, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    document = await _seed_default_document(db_session)
    await db_session.commit()

    headers = {"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"}

    initial = await client.get(f"/v1/documents/{document.id}/shares", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["shares"] == []

    added = await client.post(
        f"/v1/documents/{document.id}/shares",
        headers=headers,
        json={"tenant_ids": [test_tenant_id]},
    )
    assert added.status_code == 200
    payload = added.json()
    assert payload["document_id"] == document.id
    assert payload["owner_tenant_id"] == "default"
    assert [share["tenant_id"] for share in payload["shares"]] == [test_tenant_id]

    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "document_shares_add",
            AuditLog.target_id == document.id,
        )
    )
    assert audit_result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_default_admin_can_replace_and_remove_document_shares(
    client, db_session, default_admin_api_key, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    await _ensure_tenant(db_session, EXTRA_TENANT_ID, "Share Target Beta")
    document = await _seed_default_document(db_session)
    await db_session.commit()

    headers = {"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"}

    await client.post(
        f"/v1/documents/{document.id}/shares",
        headers=headers,
        json={"tenant_ids": [test_tenant_id]},
    )

    replaced = await client.put(
        f"/v1/documents/{document.id}/shares",
        headers=headers,
        json={"tenant_ids": [EXTRA_TENANT_ID]},
    )
    assert replaced.status_code == 200
    replaced_payload = replaced.json()
    assert [share["tenant_id"] for share in replaced_payload["shares"]] == [EXTRA_TENANT_ID]

    removed = await client.request(
        "DELETE",
        f"/v1/documents/{document.id}/shares",
        headers=headers,
        json={"tenant_ids": [EXTRA_TENANT_ID]},
    )
    assert removed.status_code == 200
    assert removed.json()["shares"] == []


@pytest.mark.asyncio
async def test_non_default_admin_cannot_manage_document_shares(
    client, api_key, db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    document = await _seed_default_document(db_session)
    await db_session.commit()

    response = await client.post(
        f"/v1/documents/{document.id}/shares",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
        json={"tenant_ids": [test_tenant_id]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_default_admin_cannot_share_document_to_default_tenant(
    client, db_session, default_admin_api_key
):
    await configure_worker_session(db_session)
    document = await _seed_default_document(db_session)
    await db_session.commit()

    response = await client.post(
        f"/v1/documents/{document.id}/shares",
        headers={"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"},
        json={"tenant_ids": ["default"]},
    )
    assert response.status_code == 400



@pytest.mark.asyncio
async def test_document_share_endpoints_reject_when_feature_disabled(
    client, db_session, default_admin_api_key, test_tenant_id, monkeypatch
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    document = await _seed_default_document(db_session)
    await db_session.commit()

    monkeypatch.setattr("src.api.routes.documents.settings.enable_document_share_management", False)

    headers = {"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"}
    responses = [
        await client.get(f"/v1/documents/{document.id}/shares", headers=headers),
        await client.post(
            f"/v1/documents/{document.id}/shares",
            headers=headers,
            json={"tenant_ids": [test_tenant_id]},
        ),
        await client.put(
            f"/v1/documents/{document.id}/shares",
            headers=headers,
            json={"tenant_ids": [test_tenant_id]},
        ),
        await client.request(
            "DELETE",
            f"/v1/documents/{document.id}/shares",
            headers=headers,
            json={"tenant_ids": [test_tenant_id]},
        ),
    ]

    for response in responses:
        assert response.status_code == 403
        assert "disabled" in response.text.lower()


@pytest.mark.asyncio
async def test_document_sharing_service_invalidates_shared_visibility_cache_on_remove(
    db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "Global Admin")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    document = await _seed_default_document(db_session)
    service = DocumentSharingService(db_session)
    await service.add_shares(document.id, [test_tenant_id], actor="test-suite")

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
    assert cached_ids == [document.id]

    await configure_worker_session(db_session)
    await service.remove_shares(document.id, [test_tenant_id], actor="test-suite")

    await db_session.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": test_tenant_id},
    )

    refreshed_ids = await repository.list_visible_document_ids(
        viewer_tenant_id=test_tenant_id,
        owner_tenant_id="default",
    )
    assert refreshed_ids == []
