import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.application.metrics.collector import QueryMetrics
from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
from src.core.admin_ops.domain.audit import AuditLog
from src.core.database.session import configure_worker_session
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.document_share import DocumentShare
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant
from src.shared.security import generate_api_key, hash_api_key

TEST_DOC_PREFIX = "share-metrics-"
TEST_KEY_NAME_PREFIX = "Share Metrics Test"


@pytest.fixture(autouse=True)
def _fail_open_rate_limit(monkeypatch):
    import src.api.middleware.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module.settings.rate_limits, "fail_open", True)
    rate_limit_module._rate_limiter = None


@pytest_asyncio.fixture(autouse=True)
async def cleanup_share_metric_artifacts(db_session: AsyncSession, test_tenant_id: str):
    await configure_worker_session(db_session)

    async def _wipe():
        await db_session.execute(
            delete(AuditLog).where(AuditLog.action.like("document_shares%"))
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
        await db_session.commit()

    await _wipe()
    yield
    await _wipe()


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
async def super_admin_api_key(db_session: AsyncSession) -> str:
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "Global Admin")

    raw_key = generate_api_key(prefix="test")
    key_record = ApiKey(
        name=f"{TEST_KEY_NAME_PREFIX} Super Admin {uuid.uuid4()}",
        prefix="test",
        hashed_key=hash_api_key(raw_key),
        last_chars=raw_key[-4:],
        is_active=True,
        scopes=["admin", "super_admin"],
    )
    db_session.add(key_record)
    await db_session.flush()
    db_session.add(ApiKeyTenant(api_key_id=key_record.id, tenant_id="default", role="admin"))
    await db_session.commit()
    return raw_key


class _StubCollector:
    async def get_recent(self, tenant_id=None, limit=100):
        return [
            QueryMetrics(
                query_id="q-shared",
                tenant_id="integration_test_tenant",
                query="shared query",
                shared_hits=5,
                local_hits=3,
                acl_filtered_results=2,
            ),
            QueryMetrics(
                query_id="q-default",
                tenant_id="default",
                query="default query",
                shared_hits=0,
                local_hits=4,
                acl_filtered_results=0,
            ),
        ]

    async def get_counter(self, name, tenant_id):
        if tenant_id != "integration_test_tenant":
            return 0
        if name == "document_visibility_denied":
            return 2
        if name == "document_visibility_not_found":
            return 1
        return 0

    async def close(self):
        return None


class _CounterCollector:
    def __init__(self):
        self.counters = {}

    async def get_recent(self, tenant_id=None, limit=100):
        return []

    async def increment_counter(self, name, tenant_id, amount=1):
        key = (name, tenant_id)
        self.counters[key] = self.counters.get(key, 0) + amount

    async def get_counter(self, name, tenant_id):
        return self.counters.get((name, tenant_id), 0)

    async def close(self):
        return None


async def _seed_shared_default_document(session: AsyncSession, target_tenant_id: str) -> Document:
    document = await _seed_default_document(session)
    session.add(
        DocumentShare(
            id=str(uuid.uuid4()),
            document_id=document.id,
            target_tenant_id=target_tenant_id,
            created_by="tester",
            share_mode="read",
        )
    )
    await session.flush()
    return document


@pytest.mark.asyncio
async def test_document_share_summary_endpoint_reports_flags_counts_and_metrics(
    client, db_session, super_admin_api_key, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "Global Admin")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    document = await _seed_default_document(db_session)

    db_session.add(
        DocumentShare(
            id=str(uuid.uuid4()),
            document_id=document.id,
            target_tenant_id=test_tenant_id,
            created_by="tester",
            share_mode="read",
        )
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    db_session.add(
        AuditLog(
            tenant_id="default",
            actor="tester",
            action="document_shares_add",
            target_type="document",
            target_id=document.id,
            timestamp=now - timedelta(minutes=5),
            changes={"added": [test_tenant_id]},
        )
    )
    db_session.add(
        AuditLog(
            tenant_id="default",
            actor="tester",
            action="document_shares_remove",
            target_type="document",
            target_id=document.id,
            timestamp=now,
            changes={"removed": [test_tenant_id]},
        )
    )
    await db_session.commit()

    with patch("src.api.routes.admin.observability.build_metrics_collector", return_value=_StubCollector()):
        response = await client.get(
            "/v1/admin/observability/document-shares/summary",
            headers={"X-API-Key": super_admin_api_key, "X-Tenant-ID": "default"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["flags"]["enable_document_share_management"] is True
    assert payload["flags"]["enable_upload_time_document_shares"] is True
    assert payload["flags"]["enable_acl_aware_vector_retrieval"] is True
    assert payload["flags"]["enable_acl_aware_graph_retrieval"] is True
    assert payload["totals"]["share_row_count"] >= 1
    assert payload["totals"]["shared_document_count"] >= 1
    assert payload["totals"]["share_add_audit_count"] == 1
    assert payload["totals"]["share_remove_audit_count"] == 1
    assert payload["query_metrics"]["recent_query_count"] == 2
    assert payload["query_metrics"]["shared_hits"] == 5
    assert payload["query_metrics"]["local_hits"] == 7
    assert payload["query_metrics"]["acl_filtered_results"] == 2

    tenant_summary = next(
        item for item in payload["tenants"] if item["tenant_id"] == test_tenant_id
    )
    assert tenant_summary["share_row_count"] == 1
    assert tenant_summary["shared_document_count"] == 1
    assert tenant_summary["denied_visibility_count"] == 2
    assert tenant_summary["not_found_visibility_count"] == 1


@pytest.mark.asyncio
async def test_document_share_audit_endpoint_returns_recent_share_events(
    client, db_session, super_admin_api_key, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "Global Admin")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    document = await _seed_default_document(db_session)
    now = datetime.now(UTC).replace(tzinfo=None)

    db_session.add(
        AuditLog(
            tenant_id="default",
            actor="tester",
            action="document_shares_add",
            target_type="document",
            target_id=document.id,
            timestamp=now - timedelta(minutes=5),
            changes={"added": [test_tenant_id]},
        )
    )
    db_session.add(
        AuditLog(
            tenant_id="default",
            actor="tester",
            action="document_shares_remove",
            target_type="document",
            target_id=document.id,
            timestamp=now,
            changes={"removed": [test_tenant_id]},
        )
    )
    await db_session.commit()

    response = await client.get(
        "/v1/admin/observability/document-shares/audit?limit=10",
        headers={"X-API-Key": super_admin_api_key, "X-Tenant-ID": "default"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["action"] for item in payload[:2]] == [
        "document_shares_remove",
        "document_shares_add",
    ]
    assert payload[0]["target_id"] == document.id


@pytest.mark.asyncio
async def test_document_visibility_counters_distinguish_denied_and_not_found(
    client, api_key, db_session, super_admin_api_key, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "Global Admin")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    await _seed_shared_default_document(db_session, test_tenant_id)
    hidden_document = await _seed_default_document(db_session)
    await db_session.commit()

    collector = _CounterCollector()

    with (
        patch("src.amber_platform.composition_root.build_metrics_collector", return_value=collector),
        patch("src.api.routes.admin.observability.build_metrics_collector", return_value=collector),
    ):
        denied_response = await client.get(
            f"/v1/documents/{hidden_document.id}",
            headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
        )
        missing_response = await client.get(
            f"/v1/documents/{uuid.uuid4()}",
            headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
        )
        summary_response = await client.get(
            "/v1/admin/observability/document-shares/summary",
            headers={"X-API-Key": super_admin_api_key, "X-Tenant-ID": "default"},
        )

    assert denied_response.status_code == 404
    assert missing_response.status_code == 404
    assert summary_response.status_code == 200

    payload = summary_response.json()
    tenant_summary = next(
        item for item in payload["tenants"] if item["tenant_id"] == test_tenant_id
    )
    assert tenant_summary["denied_visibility_count"] == 1
    assert tenant_summary["not_found_visibility_count"] == 1
