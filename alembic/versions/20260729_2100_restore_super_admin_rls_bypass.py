"""restore cross-tenant RLS visibility for privileged worker sessions

Revision ID: 20260729_2100
Revises: 20260603_1300
Create Date: 2026-07-29 21:00:00.000000

The group RLS migration accidentally kept the tenant match outside the
super-admin branch. Worker sessions use an empty current tenant together with
app.is_super_admin=true for cross-tenant maintenance, so documents and chunks
became invisible to recovery, export, backup, and provisioning tasks.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260729_2100"
down_revision = "20260603_1300"
branch_labels = None
depends_on = None


SUPER_ADMIN_OR_TENANT_POLICY = """
    current_setting('app.is_super_admin', true) = 'true'
    OR (
        tenant_id = current_setting('app.current_tenant', true)::text
        AND (
            current_setting('app.tenant_role', true) = 'admin'
            OR current_setting('app.groups_enforced', true) IS DISTINCT FROM 'true'
        )
    )
"""

TENANT_SCOPED_POLICY = """
    tenant_id = current_setting('app.current_tenant', true)::text
    AND (
        current_setting('app.is_super_admin', true) = 'true'
        OR current_setting('app.tenant_role', true) = 'admin'
        OR current_setting('app.groups_enforced', true) IS DISTINCT FROM 'true'
    )
"""


def _replace_policy(table: str, policy_name: str, expression: str) -> None:
    op.execute(sa.text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {policy_name}
            ON {table}
            FOR ALL
            USING ({expression})
            WITH CHECK ({expression})
            """
        )
    )


def upgrade() -> None:
    _replace_policy("documents", "tenant_isolation", SUPER_ADMIN_OR_TENANT_POLICY)
    _replace_policy("chunks", "tenant_isolation_chunks", SUPER_ADMIN_OR_TENANT_POLICY)


def downgrade() -> None:
    _replace_policy("documents", "tenant_isolation", TENANT_SCOPED_POLICY)
    _replace_policy("chunks", "tenant_isolation_chunks", TENANT_SCOPED_POLICY)
