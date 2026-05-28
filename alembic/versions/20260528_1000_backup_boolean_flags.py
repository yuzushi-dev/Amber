"""convert backup_schedules.enabled and backup_jobs.is_scheduled to Boolean

Revision ID: 20260528_1000
Revises: 20260521_1000
Create Date: 2026-05-28 10:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260528_1000"
down_revision = "20260521_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # backup_schedules.enabled : VARCHAR ("true"/"false") -> BOOLEAN
    op.alter_column(
        "backup_schedules",
        "enabled",
        existing_type=sa.String(),
        type_=sa.Boolean(),
        existing_nullable=False,
        postgresql_using="(enabled = 'true')",
        server_default=sa.text("false"),
    )

    # backup_jobs.is_scheduled : VARCHAR ("true"/"false") -> BOOLEAN
    op.alter_column(
        "backup_jobs",
        "is_scheduled",
        existing_type=sa.String(),
        type_=sa.Boolean(),
        existing_nullable=False,
        postgresql_using="(is_scheduled = 'true')",
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.alter_column(
        "backup_jobs",
        "is_scheduled",
        existing_type=sa.Boolean(),
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using="CASE WHEN is_scheduled THEN 'true' ELSE 'false' END",
        server_default="false",
    )
    op.alter_column(
        "backup_schedules",
        "enabled",
        existing_type=sa.Boolean(),
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using="CASE WHEN enabled THEN 'true' ELSE 'false' END",
        server_default="false",
    )
