"""add provisioning_jobs table

Revision ID: 20260327_1000
Revises: 20260325_1600
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260327_1000"
down_revision = "20260325_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provisioning_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("target_tenant_id", sa.String(), nullable=False),
        sa.Column("source_tenant_id", sa.String(), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(), nullable=True),
        sa.Column("folder_ids", postgresql.JSONB(), nullable=True),
        sa.Column("include_graph", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("docs_copied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_copied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vectors_copied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("graph_nodes_copied", sa.Integer(), nullable=False, server_default="0"),
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
    )
    op.create_index(
        "ix_provisioning_jobs_target_tenant_id",
        "provisioning_jobs",
        ["target_tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_provisioning_jobs_target_tenant_id", table_name="provisioning_jobs")
    op.drop_table("provisioning_jobs")
