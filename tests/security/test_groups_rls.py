"""
Security tests for intra-tenant groups RLS (migration 20260521_1000).

Verifies:
- The 4 group tables have RLS enabled and FORCE RLS set.
- app_visible_document_ids exists as a SQL function in the DB.
- Group enforcement isolates visibility to the caller's group folders.
- Fail-closed: groups_enforced=true with empty current_groups -> 0 documents.
- Legacy: groups_enforced unset -> full-tenant visibility (unchanged).

The data-isolation tests connect as the non-owner graphrag_app role, because
the owner role bypasses RLS even under FORCE RLS. They are skipped when no
non-owner URL is available or the DB is unreachable.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.api.config import get_settings

GROUP_TABLES = [
    "groups",
    "group_members",
    "group_folder_access",
    "group_document_access",
]

TENANT_ID = "default"


def _owner_url() -> str:
    return get_settings().db.database_url


def _app_url() -> str | None:
    """URL for the non-owner graphrag_app role, which respects RLS."""
    settings = get_settings()
    if settings.db.app_database_url:
        return settings.db.app_database_url
    env_url = os.environ.get("APP_DATABASE_URL")
    if env_url:
        return env_url
    password = os.environ.get("GRAPHRAG_APP_PASSWORD")
    if not password:
        return None
    owner = settings.db.database_url
    # postgresql+asyncpg://graphrag:pw@host:5432/db -> swap user/password
    try:
        scheme, rest = owner.split("://", 1)
        _creds, hostpart = rest.split("@", 1)
    except ValueError:
        return None
    return f"{scheme}://graphrag_app:{password}@{hostpart}"


# ── Catalog assertions (owner connection is fine here) ────────────────────────


@pytest.mark.asyncio
async def test_group_tables_have_force_rls():
    """Each group table must have RLS enabled AND FORCE RLS set."""
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relkind = 'r'
                      AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
                      AND relname = ANY(:names)
                    """
                ),
                {"names": GROUP_TABLES},
            )
            rows = {
                r.relname: (r.relrowsecurity, r.relforcerowsecurity)
                for r in result.fetchall()
            }
    finally:
        await engine.dispose()

    for table in GROUP_TABLES:
        enabled, forced = rows.get(table, (None, None))
        assert enabled is True, f"RLS not enabled on '{table}'"
        assert forced is True, f"FORCE RLS not set on '{table}'"


@pytest.mark.asyncio
async def test_app_visible_document_ids_function_exists():
    """app_visible_document_ids(text, text[]) must exist as a SECURITY DEFINER function."""
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT p.proname, p.prosecdef
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public'
                      AND p.proname = 'app_visible_document_ids'
                    """
                )
            )
            row = result.fetchone()
    finally:
        await engine.dispose()

    assert row is not None, "app_visible_document_ids function is missing"
    assert row.prosecdef is True, "app_visible_document_ids must be SECURITY DEFINER"


# ── Data-isolation assertions (require non-owner role + seed data) ────────────


async def _fetch_one_group_id(conn, name: str) -> str | None:
    result = await conn.execute(
        text(
            "SELECT id FROM groups WHERE tenant_id = :tid AND name = :name"
        ),
        {"tid": TENANT_ID, "name": name},
    )
    row = result.fetchone()
    return row[0] if row else None


async def _set_group_context(conn, groups: str) -> None:
    await conn.execute(
        text("SELECT set_config('app.current_tenant', :tid, false)"),
        {"tid": TENANT_ID},
    )
    await conn.execute(
        text("SELECT set_config('app.is_super_admin', 'false', false)")
    )
    await conn.execute(
        text("SELECT set_config('app.tenant_role', 'user', false)")
    )
    await conn.execute(
        text("SELECT set_config('app.groups_enforced', 'true', false)")
    )
    await conn.execute(
        text("SELECT set_config('app.current_groups', :g, false)"),
        {"g": groups},
    )


async def _connect_app():
    url = _app_url()
    if not url:
        pytest.skip("No non-owner DB URL (set APP_DATABASE_URL or GRAPHRAG_APP_PASSWORD)")
    engine = create_async_engine(url)
    try:
        conn = await engine.connect()
    except Exception as exc:  # unreachable DB / bad creds
        await engine.dispose()
        pytest.skip(f"Non-owner DB connection unavailable: {exc}")
    return engine, conn


@pytest.mark.asyncio
async def test_group_enforced_visibility_is_scoped_to_sales_folders():
    """With Sales group enforced, visible documents are exactly those in Sales folders."""
    engine, conn = await _connect_app()
    try:
        # Set tenant context before querying groups (required by RLS policy)
        await conn.execute(
            text("SELECT set_config('app.current_tenant', :tid, false)"),
            {"tid": TENANT_ID},
        )
        await conn.execute(text("SELECT set_config('app.is_super_admin', 'false', false)"))
        sales_id = await _fetch_one_group_id(conn, "Sales")
        if not sales_id:
            pytest.skip("Sales group not seeded; run scripts/seed_groups_local.py")

        await _set_group_context(conn, sales_id)

        visible = await conn.execute(
            text("SELECT id, folder_id FROM documents ORDER BY id")
        )
        visible_docs = visible.fetchall()

        expected = await conn.execute(
            text(
                "SELECT document_id FROM app_visible_document_ids(:tid, ARRAY[:gid])"
            ),
            {"tid": TENANT_ID, "gid": sales_id},
        )
        expected_ids = {r[0] for r in expected.fetchall()}
    finally:
        await conn.close()
        await engine.dispose()

    visible_ids = {r[0] for r in visible_docs}
    assert visible_ids == expected_ids, (
        "documents visible under Sales enforcement do not match app_visible_document_ids; "
        f"visible={visible_ids} expected={expected_ids}"
    )


@pytest.mark.asyncio
async def test_fail_closed_with_empty_current_groups():
    """groups_enforced=true with empty current_groups must reveal 0 documents."""
    engine, conn = await _connect_app()
    try:
        await _set_group_context(conn, "")
        result = await conn.execute(text("SELECT count(*) FROM documents"))
        count = result.scalar_one()
    finally:
        await conn.close()
        await engine.dispose()

    assert count == 0, (
        f"fail-closed violated: {count} documents visible with empty current_groups"
    )


@pytest.mark.asyncio
async def test_legacy_behavior_when_groups_not_enforced():
    """Without groups_enforced, a non-admin still sees the whole tenant (unchanged)."""
    engine, conn = await _connect_app()
    try:
        await conn.execute(
            text("SELECT set_config('app.current_tenant', :tid, false)"),
            {"tid": TENANT_ID},
        )
        await conn.execute(
            text("SELECT set_config('app.is_super_admin', 'false', false)")
        )
        await conn.execute(
            text("SELECT set_config('app.tenant_role', 'user', false)")
        )
        # groups_enforced intentionally NOT set
        result = await conn.execute(
            text("SELECT count(*) FROM documents WHERE tenant_id = :tid"),
            {"tid": TENANT_ID},
        )
        scoped_count = result.scalar_one()

        total = await conn.execute(
            text("SELECT count(*) FROM documents")
        )
        total_count = total.scalar_one()
    finally:
        await conn.close()
        await engine.dispose()

    assert scoped_count == total_count, (
        "legacy path changed: non-enforced visibility should equal full tenant count "
        f"(tenant-scoped={scoped_count}, all-visible={total_count})"
    )
