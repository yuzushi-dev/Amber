"""add authenticated ownership to user_facts

Revision ID: 20260812_1500
Revises: 20260804_1100
Create Date: 2026-08-12 15:00:00.000000

User facts were previously keyed only by ``user_id``, which mirrors the
caller-controlled ``X-User-ID`` header. Existing rows cannot be backfilled
because their authenticated API-key owner was never recorded; application
reads therefore fail closed for ``NULL`` owners.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260812_1500"
down_revision = "20260804_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_facts", sa.Column("api_key_id", sa.String(), nullable=True))
    op.create_index(
        "ix_user_facts_api_key_id", "user_facts", ["api_key_id"], unique=False
    )
    op.create_index(
        "ix_user_facts_tenant_api_key", "user_facts", ["tenant_id", "api_key_id"], unique=False
    )
    op.create_foreign_key(
        "fk_user_facts_api_key_id",
        "user_facts",
        "api_keys",
        ["api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_facts_api_key_id", "user_facts", type_="foreignkey")
    op.drop_index("ix_user_facts_tenant_api_key", table_name="user_facts")
    op.drop_index("ix_user_facts_api_key_id", table_name="user_facts")
    op.drop_column("user_facts", "api_key_id")
