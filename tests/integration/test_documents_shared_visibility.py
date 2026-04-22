import uuid

import pytest
from sqlalchemy import text

from src.core.database.session import configure_worker_session
from src.core.ingestion.domain.chunk import Chunk, EmbeddingStatus
from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus
from src.core.tenants.domain.tenant import Tenant


@pytest.fixture(autouse=True)
def _fail_open_rate_limit(monkeypatch):
    import src.api.middleware.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module.settings.rate_limits, "fail_open", True)
    rate_limit_module._rate_limiter = None


async def _ensure_tenant(session, tenant_id: str, name: str) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(Tenant(id=tenant_id, name=name))
        await session.flush()


async def _seed_local_document(session, tenant_id: str) -> Document:
    document = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        filename="local-team-guide.md",
        content_hash=str(uuid.uuid4()),
        storage_path=f"{tenant_id}/local-team-guide.md",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={"content_type": "text/markdown"},
    )
    session.add(document)
    await session.flush()
    return document


async def _seed_shared_default_document(
    session,
    target_tenant_id: str,
    *,
    with_chunk: bool = False,
) -> Document:
    document = Document(
        id=str(uuid.uuid4()),
        tenant_id="default",
        filename="acme-mail-admin-guide.md",
        content_hash=str(uuid.uuid4()),
        storage_path="default/acme-mail-admin-guide.md",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={"content_type": "text/markdown"},
    )
    session.add(document)
    await session.flush()

    if with_chunk:
        session.add(
            Chunk(
                id=str(uuid.uuid4()),
                tenant_id="default",
                document_id=document.id,
                index=0,
                content="Shared Acme Mail admin content",
                tokens=6,
                metadata_={},
                embedding_status=EmbeddingStatus.COMPLETED,
            )
        )

    await session.execute(
        text(
            """
            INSERT INTO document_shares (id, document_id, target_tenant_id, created_by, share_mode)
            VALUES (:id, :document_id, :target_tenant_id, :created_by, :share_mode)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "document_id": document.id,
            "target_tenant_id": target_tenant_id,
            "created_by": "test-suite",
            "share_mode": "read",
        },
    )
    await session.flush()
    return document


async def _seed_unshared_default_document(
    session,
    *,
    with_chunk: bool = False,
) -> Document:
    document = Document(
        id=str(uuid.uuid4()),
        tenant_id="default",
        filename="acme-mail-private-admin-guide.md",
        content_hash=str(uuid.uuid4()),
        storage_path="default/acme-mail-private-admin-guide.md",
        status=DocumentStatus.READY,
        source_type="upload",
        metadata_={"content_type": "text/markdown"},
    )
    session.add(document)
    await session.flush()

    if with_chunk:
        session.add(
            Chunk(
                id=str(uuid.uuid4()),
                tenant_id="default",
                document_id=document.id,
                index=0,
                content="Private Acme Mail admin content",
                tokens=5,
                metadata_={},
                embedding_status=EmbeddingStatus.COMPLETED,
            )
        )

    await session.flush()
    return document


@pytest.mark.asyncio
async def test_list_documents_includes_visibility_metadata_for_local_docs(
    client, api_key, db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    local_document = await _seed_local_document(db_session, test_tenant_id)
    await db_session.commit()

    response = await client.get(
        "/v1/documents",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
    )

    assert response.status_code == 200
    payload = response.json()
    by_id = {item["id"]: item for item in payload}
    assert local_document.id in by_id
    assert by_id[local_document.id]["is_shared"] is False
    assert by_id[local_document.id]["owner_tenant_id"] == test_tenant_id
    assert by_id[local_document.id]["visible_from_tenant_id"] == test_tenant_id
    assert by_id[local_document.id]["share_mode"] is None


@pytest.mark.asyncio
async def test_get_document_includes_visibility_metadata_for_local_docs(
    client, api_key, db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    local_document = await _seed_local_document(db_session, test_tenant_id)
    await db_session.commit()

    response = await client.get(
        f"/v1/documents/{local_document.id}",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == local_document.id
    assert payload["is_shared"] is False
    assert payload["owner_tenant_id"] == test_tenant_id
    assert payload["visible_from_tenant_id"] == test_tenant_id
    assert payload["share_mode"] is None


@pytest.mark.asyncio
async def test_list_documents_includes_shared_default_docs_for_target_tenant(
    client, api_key, db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "System Default")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    shared_document = await _seed_shared_default_document(db_session, test_tenant_id)
    await db_session.commit()

    response = await client.get(
        "/v1/documents",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
    )

    assert response.status_code == 200
    payload = response.json()
    by_id = {item["id"]: item for item in payload}
    assert shared_document.id in by_id
    assert by_id[shared_document.id]["is_shared"] is True
    assert by_id[shared_document.id]["owner_tenant_id"] == "default"
    assert by_id[shared_document.id]["visible_from_tenant_id"] == test_tenant_id
    assert by_id[shared_document.id]["share_mode"] == "read"


@pytest.mark.asyncio
async def test_shared_document_chunks_are_visible_to_target_tenant(
    client, api_key, db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "System Default")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    shared_document = await _seed_shared_default_document(
        db_session, test_tenant_id, with_chunk=True
    )
    await db_session.commit()

    response = await client.get(
        f"/v1/documents/{shared_document.id}/chunks",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["content"] == "Shared Acme Mail admin content"


@pytest.mark.asyncio
async def test_list_documents_excludes_unshared_default_docs_for_target_tenant(
    client, api_key, db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "System Default")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    hidden_document = await _seed_unshared_default_document(db_session)
    await db_session.commit()

    response = await client.get(
        "/v1/documents",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
    )

    assert response.status_code == 200
    visible_ids = {item["id"] for item in response.json()}
    assert hidden_document.id not in visible_ids


@pytest.mark.asyncio
async def test_unshared_default_document_detail_and_chunks_are_hidden_from_target_tenant(
    client, api_key, db_session, test_tenant_id
):
    await configure_worker_session(db_session)
    await _ensure_tenant(db_session, "default", "System Default")
    await _ensure_tenant(db_session, test_tenant_id, "Integration Test Tenant")
    hidden_document = await _seed_unshared_default_document(db_session, with_chunk=True)
    await db_session.commit()

    detail_response = await client.get(
        f"/v1/documents/{hidden_document.id}",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
    )
    chunks_response = await client.get(
        f"/v1/documents/{hidden_document.id}/chunks",
        headers={"X-API-Key": api_key, "X-Tenant-ID": test_tenant_id},
    )

    assert detail_response.status_code == 404
    assert chunks_response.status_code == 404
