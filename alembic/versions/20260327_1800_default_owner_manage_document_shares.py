"""allow default tenant owners to manage document_shares

Revision ID: 20260327_1800
Revises: 20260327_1600
Create Date: 2026-03-27 18:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260327_1800"
down_revision = "20260327_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS document_shares_target_read ON document_shares"))
    op.execute(sa.text("DROP POLICY IF EXISTS document_shares_super_admin_manage ON document_shares"))

    op.execute(
        sa.text(
            """
            CREATE POLICY document_shares_read_visible
            ON document_shares
            FOR SELECT
            USING (
                current_setting('app.is_super_admin', true) = 'true'
                OR target_tenant_id = current_setting('app.current_tenant', true)::text
                OR EXISTS (
                    SELECT 1
                    FROM documents d
                    WHERE d.id = document_shares.document_id
                      AND d.tenant_id = current_setting('app.current_tenant', true)::text
                )
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE POLICY document_shares_owner_manage
            ON document_shares
            FOR ALL
            USING (
                current_setting('app.is_super_admin', true) = 'true'
                OR EXISTS (
                    SELECT 1
                    FROM documents d
                    WHERE d.id = document_shares.document_id
                      AND d.tenant_id = current_setting('app.current_tenant', true)::text
                )
            )
            WITH CHECK (
                current_setting('app.is_super_admin', true) = 'true'
                OR EXISTS (
                    SELECT 1
                    FROM documents d
                    WHERE d.id = document_shares.document_id
                      AND d.tenant_id = current_setting('app.current_tenant', true)::text
                )
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS document_shares_owner_manage ON document_shares"))
    op.execute(sa.text("DROP POLICY IF EXISTS document_shares_read_visible ON document_shares"))

    op.execute(
        sa.text(
            """
            CREATE POLICY document_shares_target_read
            ON document_shares
            FOR SELECT
            USING (
                target_tenant_id = current_setting('app.current_tenant', true)::text
                OR current_setting('app.is_super_admin', true) = 'true'
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE POLICY document_shares_super_admin_manage
            ON document_shares
            FOR ALL
            USING (current_setting('app.is_super_admin', true) = 'true')
            WITH CHECK (current_setting('app.is_super_admin', true) = 'true')
            """
        )
    )
