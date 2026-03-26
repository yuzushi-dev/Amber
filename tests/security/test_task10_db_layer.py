"""
Security tests for Task 10: DB-layer tenant isolation.

Verifies:
- graphrag_app role exists and is non-superuser / non-BYPASSRLS
- Every tenant-scoped table has RLS enabled
- worker session helper sets app.is_super_admin
- Worker source files don't create sessions without setting is_super_admin
- config.py exposes app_database_url field
"""

import inspect
import pytest


# ── DB role properties ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graphrag_app_role_is_non_superuser():
    """
    graphrag_app role must be non-superuser and must not have BYPASSRLS.
    Without this, RLS policies are bypassed regardless of FORCE RLS.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    from src.api.config import get_settings
    settings = get_settings()

    engine = create_async_engine(settings.db.database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT rolname, rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = 'graphrag_app'
            """))
            row = result.fetchone()
    finally:
        await engine.dispose()

    assert row is not None, (
        "graphrag_app role does not exist. "
        "Without a non-owner role, RLS policies are bypassed by the superuser owner."
    )
    assert row.rolsuper is False, "graphrag_app must not be a superuser"
    assert row.rolbypassrls is False, "graphrag_app must not have BYPASSRLS"


@pytest.mark.asyncio
async def test_tenant_tables_have_rls_enabled():
    """Every tenant-scoped table must have row-level security enabled."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    from src.api.config import get_settings
    settings = get_settings()

    tenant_tables = [
        "documents", "chunks", "feedbacks", "folders", "audit_logs",
        "connector_states", "conversation_summaries", "graph_edit_history",
    ]

    engine = create_async_engine(settings.db.database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT relname, relrowsecurity
                FROM pg_class
                WHERE relkind = 'r'
                  AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
                  AND relname = ANY(:names)
            """), {"names": tenant_tables})
            rows = {r.relname: r.relrowsecurity for r in result.fetchall()}
    finally:
        await engine.dispose()

    for table in tenant_tables:
        assert rows.get(table) is True, (
            f"RLS not enabled on '{table}'. "
            "Tenant data can be read cross-tenant when app.current_tenant is not set."
        )


# ── Worker session helper ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_configure_worker_session_sets_super_admin():
    """configure_worker_session must SET app.is_super_admin = true in the DB session."""
    from unittest.mock import AsyncMock, MagicMock
    from sqlalchemy import text
    from src.core.database.session import configure_worker_session

    session = MagicMock()
    session.execute = AsyncMock()
    await configure_worker_session(session)

    # Extract the SQL text from each call (TextClause.text contains the SQL)
    sql_texts = []
    for call_args in session.execute.call_args_list:
        arg = call_args.args[0] if call_args.args else None
        if arg is not None:
            sql_texts.append(getattr(arg, "text", str(arg)))
    assert any("is_super_admin" in s for s in sql_texts), (
        "configure_worker_session did not call SET app.is_super_admin. "
        f"Worker sessions would be blocked by RLS on document/chunk queries. SQL seen: {sql_texts}"
    )


# ── Config field ──────────────────────────────────────────────────────────────


def test_config_has_app_database_url():
    """Settings must expose app_database_url for the non-owner role."""
    from src.api.config import get_settings
    settings = get_settings()
    assert hasattr(settings.db, "app_database_url"), (
        "Settings.db is missing app_database_url field. "
        "Cannot point the app at the non-owner graphrag_app role."
    )


# ── Worker source doesn't create bare sessions ────────────────────────────────


def _check_worker_file(path: str) -> list[str]:
    """Return list of bare session blocks that don't call configure_worker_session."""
    import re
    with open(path) as f:
        source = f.read()

    issues = []
    # Find async with async_session() as session: blocks
    # and check if configure_worker_session is called nearby
    blocks = list(re.finditer(r'async with async_session\(\) as session:', source))
    for m in blocks:
        # look at the next ~500 chars for configure_worker_session
        window = source[m.start(): m.start() + 600]
        if "configure_worker_session" not in window:
            # Get line number
            line_no = source[:m.start()].count('\n') + 1
            issues.append(f"line {line_no}: bare session without configure_worker_session")
    return issues


def test_backup_tasks_sessions_set_super_admin():
    """backup_tasks.py worker sessions must call configure_worker_session."""
    issues = _check_worker_file("/root/amber2/src/workers/backup_tasks.py")
    assert not issues, (
        f"backup_tasks.py has unguarded sessions: {issues}\n"
        "Worker sessions can bypass RLS and see cross-tenant data."
    )


def test_export_tasks_sessions_set_super_admin():
    """export_tasks.py worker sessions must call configure_worker_session."""
    issues = _check_worker_file("/root/amber2/src/workers/export_tasks.py")
    assert not issues, f"export_tasks.py has unguarded sessions: {issues}"


def test_tasks_py_sessions_set_super_admin():
    """tasks.py worker sessions must call configure_worker_session."""
    issues = _check_worker_file("/root/amber2/src/workers/tasks.py")
    assert not issues, f"tasks.py has unguarded sessions: {issues}"


def test_recovery_py_sessions_set_super_admin():
    """recovery.py worker sessions must call configure_worker_session."""
    issues = _check_worker_file("/root/amber2/src/workers/recovery.py")
    assert not issues, f"recovery.py has unguarded sessions: {issues}"
