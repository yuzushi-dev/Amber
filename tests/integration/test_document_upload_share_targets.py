import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
from src.core.admin_ops.domain.audit import AuditLog
from src.core.database.session import configure_worker_session
from src.core.ingestion.domain.document import Document
from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
from src.core.tenants.domain.tenant import Tenant
from src.shared.security import generate_api_key, hash_api_key

TEST_DOC_PREFIX = "upload-share-targets-"
TEST_KEY_NAME_PREFIX = "Upload Share Targets Test"
EXTRA_TENANT_ID = "upload-share-target-beta"


@pytest.fixture(autouse=True)
def _fail_open_rate_limit(monkeypatch):
    import src.api.middleware.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module.settings.rate_limits, "fail_open", True)
    rate_limit_module._rate_limiter = None


@pytest.fixture(autouse=True)
def _stub_storage_upload(monkeypatch):
    def _upload_file(self, object_name, data, length, content_type="application/octet-stream"):
        return None

    monkeypatch.setattr(MinIOClient, "upload_file", _upload_file)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_upload_share_artifacts(db_session: AsyncSession):
    await configure_worker_session(db_session)

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


async def _ensure_tenant(session: AsyncSession, tenant_id: str, name: str) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(Tenant(id=tenant_id, name=name))
        await session.flush()


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


@pytest_asyncio.fixture
async def non_default_admin_api_key(db_session: AsyncSession, test_tenant_id: str) -> str:
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")

    raw_key = generate_api_key(prefix="test")
    key_record = ApiKey(
        name=f"{TEST_KEY_NAME_PREFIX} Tenant Admin {uuid.uuid4()}",
        prefix="test",
        hashed_key=hash_api_key(raw_key),
        last_chars=raw_key[-4:],
        is_active=True,
        scopes=["admin", "read", "write"],
    )
    db_session.add(key_record)
    await db_session.flush()
    db_session.add(
        ApiKeyTenant(api_key_id=key_record.id, tenant_id=test_tenant_id, role="admin")
    )
    await db_session.commit()
    return raw_key


@pytest.mark.asyncio
async def test_default_upload_with_share_targets_creates_document_shares(
    client, db_session, default_admin_api_key, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    await _ensure_tenant(db_session, EXTRA_TENANT_ID, "Upload Share Target Beta")
    await db_session.commit()

    filename = f"{TEST_DOC_PREFIX}{uuid.uuid4()}.md"
    response = await client.post(
        "/v1/documents",
        headers={"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"},
        files={"file": (filename, b"# shared upload\ncontent", "text/markdown")},
        data={
            "shared_with_tenant_ids": json.dumps([test_tenant_id, EXTRA_TENANT_ID]),
        },
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    document_id = payload["document_id"]

    shares = await client.get(
        f"/v1/documents/{document_id}/shares",
        headers={"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"},
    )
    assert shares.status_code == 200
    assert [share["tenant_id"] for share in shares.json()["shares"]] == [
        test_tenant_id,
        EXTRA_TENANT_ID,
    ]

    document = await db_session.get(Document, document_id)
    assert document is not None
    assert document.tenant_id == "default"
    assert document.filename == filename

    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "document_shares_add",
            AuditLog.target_id == document_id,
        )
    )
    assert audit_result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_non_default_upload_rejects_share_targets(
    client, db_session, non_default_admin_api_key, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    await _ensure_tenant(db_session, EXTRA_TENANT_ID, "Upload Share Target Beta")
    await db_session.commit()

    response = await client.post(
        "/v1/documents",
        headers={"X-API-Key": non_default_admin_api_key, "X-Tenant-ID": test_tenant_id},
        files={
            "file": (
                f"{TEST_DOC_PREFIX}{uuid.uuid4()}.md",
                b"# tenant private upload\ncontent",
                "text/markdown",
            )
        },
        data={
            "shared_with_tenant_ids": json.dumps([EXTRA_TENANT_ID]),
        },
    )
    assert response.status_code == 400
    assert "default tenant" in response.text.lower()


@pytest.mark.asyncio
async def test_default_upload_without_share_targets_remains_private(
    client, db_session, default_admin_api_key
):
    await configure_worker_session(db_session)

    response = await client.post(
        "/v1/documents",
        headers={"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"},
        files={
            "file": (
                f"{TEST_DOC_PREFIX}{uuid.uuid4()}.md",
                b"# private upload\ncontent",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["document_id"]

    shares = await client.get(
        f"/v1/documents/{document_id}/shares",
        headers={"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"},
    )
    assert shares.status_code == 200
    assert shares.json()["shares"] == []



@pytest.mark.asyncio
async def test_default_upload_rejects_share_targets_when_feature_disabled(
    client, db_session, default_admin_api_key, test_tenant_id, monkeypatch
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    await db_session.commit()

    monkeypatch.setattr("src.api.routes.documents.settings.enable_upload_time_document_shares", False)

    response = await client.post(
        "/v1/documents",
        headers={"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"},
        files={
            "file": (
                f"{TEST_DOC_PREFIX}{uuid.uuid4()}.md",
                b"# shared upload disabled\ncontent",
                "text/markdown",
            )
        },
        data={"shared_with_tenant_ids": json.dumps([test_tenant_id])},
    )
    assert response.status_code == 403
    assert "disabled" in response.text.lower()


@pytest.mark.asyncio
async def test_default_upload_without_share_targets_still_works_when_feature_disabled(
    client, db_session, default_admin_api_key, monkeypatch
):
    await configure_worker_session(db_session)
    monkeypatch.setattr("src.api.routes.documents.settings.enable_upload_time_document_shares", False)

    response = await client.post(
        "/v1/documents",
        headers={"X-API-Key": default_admin_api_key, "X-Tenant-ID": "default"},
        files={
            "file": (
                f"{TEST_DOC_PREFIX}{uuid.uuid4()}.md",
                b"# private upload while share feature off\ncontent",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 202, response.text
