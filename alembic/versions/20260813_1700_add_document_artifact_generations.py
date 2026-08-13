"""add lossless document artifact generations

Revision ID: 20260813_1700
Revises: 20260812_1600
Create Date: 2026-08-13 17:00:00.000000

Existing documents and chunks deliberately remain NULL/legacy. The migration
does not rewrite content, enqueue ingestion, or delete artifacts.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260813_1700"
down_revision = "20260812_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_generations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_generations_document_id", "document_generations", ["document_id"]
    )
    op.create_index("ix_document_generations_tenant_id", "document_generations", ["tenant_id"])
    op.create_index("ix_document_generations_status", "document_generations", ["status"])

    op.add_column("documents", sa.Column("active_generation_id", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("pending_generation_id", sa.String(), nullable=True))
    op.create_index(
        "ix_documents_active_generation_id", "documents", ["active_generation_id"]
    )
    op.create_index(
        "ix_documents_pending_generation_id", "documents", ["pending_generation_id"]
    )
    op.create_foreign_key(
        "fk_documents_active_generation_id",
        "documents",
        "document_generations",
        ["active_generation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_documents_pending_generation_id",
        "documents",
        "document_generations",
        ["pending_generation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("chunks", sa.Column("generation_id", sa.String(), nullable=True))
    op.create_index("ix_chunks_generation_id", "chunks", ["generation_id"])
    op.create_index(
        "ix_chunks_document_generation", "chunks", ["document_id", "generation_id"]
    )
    op.create_foreign_key(
        "fk_chunks_generation_id",
        "chunks",
        "document_generations",
        ["generation_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    generation_count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM document_generations "
            "WHERE status <> 'failed' OR id IN ("
            "SELECT active_generation_id FROM documents WHERE active_generation_id IS NOT NULL)"
        )
    ).scalar_one()
    if generation_count:
        raise RuntimeError("document generation data exists; downgrade would discard it")

    op.drop_constraint("fk_chunks_generation_id", "chunks", type_="foreignkey")
    op.drop_index("ix_chunks_document_generation", table_name="chunks")
    op.drop_index("ix_chunks_generation_id", table_name="chunks")
    op.drop_column("chunks", "generation_id")
    op.drop_constraint("fk_documents_pending_generation_id", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_active_generation_id", "documents", type_="foreignkey")
    op.drop_index("ix_documents_pending_generation_id", table_name="documents")
    op.drop_index("ix_documents_active_generation_id", table_name="documents")
    op.drop_column("documents", "pending_generation_id")
    op.drop_column("documents", "active_generation_id")
    op.drop_index("ix_document_generations_status", table_name="document_generations")
    op.drop_index("ix_document_generations_tenant_id", table_name="document_generations")
    op.drop_index("ix_document_generations_document_id", table_name="document_generations")
    op.drop_table("document_generations")
