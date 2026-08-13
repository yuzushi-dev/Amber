"""add api_key_id to conversation_summaries

Revision ID: 20260803_1200
Revises: 20260729_2100
Create Date: 2026-08-03 12:00:00.000000

Issue #72: admin metrics group attribution and conversation-history ownership
checks both keyed on `conversation_summaries.user_id`, which mirrors the
caller-controlled `X-User-ID` header (see `query.py::_get_user_id`), not an
authenticated identity. This column stores the authenticated API key's
immutable `id` at write time instead.

Nullable and unindexed-for-uniqueness by design: existing rows have no
recorded authenticated identity and cannot be backfilled from data that was
never captured. Application code (query.py, admin/chat_history.py) treats
NULL as "no verified identity" and fails closed on every security-relevant
read and write (history re-injection, group lookup, and conversation updates).
Legacy rows are never backfilled or adopted because their original owner
cannot be reconstructed.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_1200"
down_revision = "20260729_2100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_summaries",
        sa.Column("api_key_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_conversation_summaries_api_key_id",
        "conversation_summaries",
        ["api_key_id"],
    )
    op.create_foreign_key(
        "fk_conversation_summaries_api_key_id",
        "conversation_summaries",
        "api_keys",
        ["api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_conversation_summaries_api_key_id", "conversation_summaries", type_="foreignkey"
    )
    op.drop_index("ix_conversation_summaries_api_key_id", table_name="conversation_summaries")
    op.drop_column("conversation_summaries", "api_key_id")
