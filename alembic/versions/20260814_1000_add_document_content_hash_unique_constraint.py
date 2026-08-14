"""Add unique constraint on documents (tenant_id, content_hash).

Revision ID: 20260814_1000
Revises: 20260813_1700
Create Date: 2026-08-14 10:00:00.000000

Closes the gap left by application-only deduplication in
`UploadDocumentUseCase` / `IngestionService.register_document`: two
concurrent uploads of the same content for the same tenant can both pass
the `find_by_content_hash` check-then-act read before either commits,
producing duplicate `documents` rows for identical content. This migration
adds a database-level invariant so one of the two concurrent inserts fails
fast with an IntegrityError instead of silently duplicating data; the
application layer is responsible for turning that IntegrityError into a
clean "deduplicated" response (see `UploadDocumentUseCase.execute`).

`processing_attempt_id` already exists on `documents` (added by
20260813_1700_add_document_artifact_generations.py) - this migration only
adds the missing unique constraint.

PRE-DEPLOY GATE (manual, run against prod before applying this migration):
`ADD CONSTRAINT UNIQUE` fails outright if existing rows already violate it.
Run this read-only query first and resolve any rows it returns:

    SELECT tenant_id, content_hash, count(*)
    FROM documents
    GROUP BY tenant_id, content_hash
    HAVING count(*) > 1;

The `upgrade()` step below also runs this check itself and raises before
attempting to add the constraint, so an accidental apply against a dataset
with pre-existing duplicates fails loudly instead of raising a raw
Postgres error.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_1000"
down_revision: str | None = "20260813_1700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    duplicate_count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "SELECT tenant_id, content_hash FROM documents "
                "GROUP BY tenant_id, content_hash HAVING count(*) > 1"
                ") dupes"
            )
        )
        .scalar_one()
    )
    if duplicate_count:
        raise RuntimeError(
            f"documents has {duplicate_count} existing (tenant_id, content_hash) "
            "duplicate group(s); resolve them before adding "
            "uq_documents_tenant_content_hash (see the query in this migration's "
            "module docstring)"
        )

    op.create_unique_constraint(
        "uq_documents_tenant_content_hash", "documents", ["tenant_id", "content_hash"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_tenant_content_hash", "documents", type_="unique")
