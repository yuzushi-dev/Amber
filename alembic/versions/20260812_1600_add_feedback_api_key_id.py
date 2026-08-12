"""add authenticated ownership to feedback rows

Revision ID: 20260812_1600
Revises: 20260812_1500
Create Date: 2026-08-12 16:00:00.000000

Feedback rows created before ownership was recorded remain nullable and are
excluded from user-facing reads and updates.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260812_1600"
down_revision = "20260812_1500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedbacks", sa.Column("api_key_id", sa.String(), nullable=True))
    op.create_index("ix_feedbacks_api_key_id", "feedbacks", ["api_key_id"], unique=False)
    op.create_foreign_key(
        "fk_feedbacks_api_key_id",
        "feedbacks",
        "api_keys",
        ["api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_feedbacks_api_key_id", "feedbacks", type_="foreignkey")
    op.drop_index("ix_feedbacks_api_key_id", table_name="feedbacks")
    op.drop_column("feedbacks", "api_key_id")
