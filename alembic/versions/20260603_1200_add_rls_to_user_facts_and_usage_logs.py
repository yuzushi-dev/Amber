"""Add RLS to user_facts and usage_logs

Revision ID: 20260603_1200
Revises: 20260528_1100
Create Date: 2026-06-03 12:00:00.000000

Both tables carry tenant_id but had no Postgres RLS.  Tenant isolation was
purely application-side (WHERE tenant_id = ...).  A query that forgets the
predicate could leak cross-tenant data.  This migration mirrors the existing
tenant-isolation policy idiom used by documents, chunks, connector_states, etc.

Policy idiom copied from 20260521_1000_add_groups.py (GROUP_TABLES loop):

    CREATE POLICY tenant_isolation_<table>
    ON <table>
    FOR ALL
    USING (
        tenant_id = current_setting('app.current_tenant', true)::text
        OR current_setting('app.is_super_admin', true) = 'true'
    )
    WITH CHECK (
        tenant_id = current_setting('app.current_tenant', true)::text
        OR current_setting('app.is_super_admin', true) = 'true'
    )

Write-path notes
----------------
* user_facts: ConversationMemoryManager._configure_session() sets
  app.current_tenant before every INSERT/UPDATE/DELETE.  Under FORCE RLS the
  INSERT passes because tenant_id matches app.current_tenant.  Worker/restore
  sessions that touch user_facts already call configure_worker_session() which
  sets app.is_super_admin='true', so they pass via the super-admin bypass.

* usage_logs: UsageTracker.record_usage() previously opened a raw
  async_session_maker() session with no GUCs set.  Under FORCE RLS the INSERT
  would fail because current_setting('app.current_tenant', true) returns NULL
  and NULL = tenant_id is false.  usage_tracker.py has been patched (same
  commit) to call configure_worker_session() — which sets
  app.is_super_admin='true' — before every INSERT, matching the pattern used
  by background workers.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260603_1200"
down_revision = "20260528_1100"
branch_labels = None
depends_on = None

TABLES = [
    "user_facts",
    "usage_logs",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_{table}
                ON {table}
                FOR ALL
                USING (
                    tenant_id = current_setting('app.current_tenant', true)::text
                    OR current_setting('app.is_super_admin', true) = 'true'
                )
                WITH CHECK (
                    tenant_id = current_setting('app.current_tenant', true)::text
                    OR current_setting('app.is_super_admin', true) = 'true'
                )
                """
            )
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(
            sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        )
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
