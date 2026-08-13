"""Add document processing ownership and tenant content uniqueness.

Revision ID: 20260813_processing_ownership
Revises: 20260804_1100
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_processing_ownership"
down_revision: str | None = "20260804_1100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("processing_attempt_id", sa.String(), nullable=True))
    op.create_index(
        "ix_documents_processing_attempt_id",
        "documents",
        ["processing_attempt_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_documents_tenant_content_hash",
        "documents",
        ["tenant_id", "content_hash"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_tenant_content_hash", "documents", type_="unique")
    op.drop_index("ix_documents_processing_attempt_id", table_name="documents")
    op.drop_column("documents", "processing_attempt_id")
