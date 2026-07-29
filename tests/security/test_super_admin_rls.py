"""Regression tests for cross-tenant super-admin RLS visibility."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.api.config import get_settings


async def _set_rls_context(
    connection,
    *,
    tenant_id: str,
    is_super_admin: bool,
    groups_enforced: bool = False,
) -> None:
    await connection.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )
    await connection.execute(
        text("SELECT set_config('app.is_super_admin', :enabled, true)"),
        {"enabled": "true" if is_super_admin else "false"},
    )
    await connection.execute(
        text("SELECT set_config('app.tenant_role', 'user', true)")
    )
    await connection.execute(
        text("SELECT set_config('app.groups_enforced', :enabled, true)"),
        {"enabled": "true" if groups_enforced else "false"},
    )
    await connection.execute(
        text("SELECT set_config('app.current_groups', '', true)")
    )


@pytest.mark.asyncio
async def test_super_admin_bypasses_tenant_rls_without_current_tenant():
    """Workers marked super-admin must see documents and chunks across tenants."""
    suffix = uuid4().hex
    tenant_ids = [f"rls_test_t1_{suffix}", f"rls_test_t2_{suffix}"]
    document_ids = [f"rls_test_doc1_{suffix}", f"rls_test_doc2_{suffix}"]
    chunk_ids = [f"rls_test_chunk1_{suffix}", f"rls_test_chunk2_{suffix}"]

    engine = create_async_engine(get_settings().db.database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        for index, tenant_id in enumerate(tenant_ids):
            await connection.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, is_active, config, metadata_json)
                    VALUES (:id, :name, true, '{}'::json, '{}'::json)
                    """
                ),
                {"id": tenant_id, "name": f"RLS test tenant {index + 1}"},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO documents (
                        id, tenant_id, filename, content_hash, storage_path,
                        status, source_type, metadata, keywords, hashtags, updated_at
                    )
                    VALUES (
                        :id, :tenant_id, :filename, :content_hash, :storage_path,
                        'INGESTED', 'upload', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                        now() - interval '1 hour'
                    )
                    """
                ),
                {
                    "id": document_ids[index],
                    "tenant_id": tenant_id,
                    "filename": f"rls-test-{index + 1}.md",
                    "content_hash": f"rls-test-hash-{index + 1}-{suffix}",
                    "storage_path": f"{tenant_id}/rls-test-{index + 1}.md",
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO chunks (
                        id, tenant_id, document_id, index, content, tokens,
                        metadata, embedding_status
                    )
                    VALUES (
                        :id, :tenant_id, :document_id, 0, :content, 4,
                        '{}'::jsonb, 'COMPLETED'
                    )
                    """
                ),
                {
                    "id": chunk_ids[index],
                    "tenant_id": tenant_id,
                    "document_id": document_ids[index],
                    "content": f"RLS test chunk {index + 1}",
                },
            )

        await connection.execute(text("SET LOCAL ROLE graphrag_app"))

        from src.workers.recovery import recover_stale_documents

        fake_engine = MagicMock()
        fake_engine.dispose = AsyncMock()

        def _transaction_bound_sessionmaker(*args, **kwargs):
            return lambda: AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )

        with (
            patch(
                "src.workers.recovery.create_async_engine",
                return_value=fake_engine,
            ) as create_engine,
            patch(
                "src.workers.recovery.sessionmaker",
                side_effect=_transaction_bound_sessionmaker,
            ),
            patch("src.workers.recovery._publish_recovery_status"),
            patch("src.workers.tasks.process_document") as process_document,
        ):
            recovery_result = await recover_stale_documents()

        expected_url = (
            get_settings().db.app_database_url
            or get_settings().db.database_url
        )
        create_engine.assert_called_once_with(expected_url)
        assert recovery_result["total"] > 0
        assert process_document.delay.call_count == recovery_result["recovered"]

        await _set_rls_context(
            connection,
            tenant_id="",
            is_super_admin=True,
            groups_enforced=True,
        )
        visible_to_super_admin = (
            await connection.execute(
                text("SELECT id FROM documents WHERE id = ANY(:ids) ORDER BY id"),
                {"ids": document_ids},
            )
        ).scalars().all()

        assert visible_to_super_admin == sorted(document_ids)
        visible_chunks_to_super_admin = (
            await connection.execute(
                text("SELECT id FROM chunks WHERE id = ANY(:ids) ORDER BY id"),
                {"ids": chunk_ids},
            )
        ).scalars().all()

        assert visible_chunks_to_super_admin == sorted(chunk_ids)

        await _set_rls_context(
            connection,
            tenant_id=tenant_ids[0],
            is_super_admin=False,
        )
        visible_to_tenant = (
            await connection.execute(
                text("SELECT id FROM documents WHERE id = ANY(:ids) ORDER BY id"),
                {"ids": document_ids},
            )
        ).scalars().all()

        assert visible_to_tenant == [document_ids[0]]

        await _set_rls_context(
            connection,
            tenant_id=tenant_ids[0],
            is_super_admin=False,
            groups_enforced=True,
        )
        visible_without_groups = (
            await connection.execute(
                text("SELECT id FROM documents WHERE id = ANY(:ids)"),
                {"ids": document_ids},
            )
        ).scalars().all()

        assert visible_without_groups == []
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
