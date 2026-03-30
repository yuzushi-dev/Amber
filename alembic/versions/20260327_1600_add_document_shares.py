"""add document_shares table and shared read visibility policies

Revision ID: 20260327_1600
Revises: 20260327_1000
Create Date: 2026-03-27 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260327_1600"
down_revision = "20260327_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_shares",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("share_mode", sa.String(), nullable=False, server_default="read"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "document_id",
            "target_tenant_id",
            name="uq_document_shares_document_target_tenant",
        ),
    )
    op.create_index(
        "ix_document_shares_document_id", "document_shares", ["document_id"]
    )
    op.create_index(
        "ix_document_shares_target_tenant_id", "document_shares", ["target_tenant_id"]
    )

    op.execute(sa.text("ALTER TABLE document_shares ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE document_shares FORCE ROW LEVEL SECURITY"))

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
    op.execute(
        sa.text(
            """
            CREATE POLICY documents_shared_read
            ON documents
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1
                    FROM document_shares ds
                    WHERE ds.document_id = documents.id
                      AND ds.target_tenant_id = current_setting('app.current_tenant', true)::text
                )
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE POLICY chunks_shared_read
            ON chunks
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1
                    FROM document_shares ds
                    WHERE ds.document_id = chunks.document_id
                      AND ds.target_tenant_id = current_setting('app.current_tenant', true)::text
                )
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS chunks_shared_read ON chunks"))
    op.execute(sa.text("DROP POLICY IF EXISTS documents_shared_read ON documents"))
    op.execute(
        sa.text("DROP POLICY IF EXISTS document_shares_super_admin_manage ON document_shares")
    )
    op.execute(sa.text("DROP POLICY IF EXISTS document_shares_target_read ON document_shares"))
    op.execute(sa.text("ALTER TABLE document_shares NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE document_shares DISABLE ROW LEVEL SECURITY"))

    op.drop_index("ix_document_shares_target_tenant_id", table_name="document_shares")
    op.drop_index("ix_document_shares_document_id", table_name="document_shares")
    op.drop_table("document_shares")
