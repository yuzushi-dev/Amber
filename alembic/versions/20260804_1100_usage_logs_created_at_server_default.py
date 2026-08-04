"""add server_default to usage_logs.created_at/updated_at

Revision ID: 20260804_1100
Revises: 20260803_1200
Create Date: 2026-08-04 11:00:00.000000

Root cause: alembic/versions/20260119_1200_add_usage_logs_table.py created
`created_at`/`updated_at` as plain nullable timestamps with no server-side
default. The ORM model (`src/core/admin_ops/domain/usage.py::UsageLog`, via
`TimestampMixin`) has always declared `server_default=func.now()`, but the
live schema never matched it. The only writer, `UsageTracker.record_usage()`
(`src/core/admin_ops/application/usage_tracker.py`), builds `UsageLog(...)`
through the ORM without setting `created_at` explicitly, so SQLAlchemy's
Python-side `default=_utcnow` has always populated it correctly on that path
-- confirmed on prod: rows inserted today are fully timestamped, and the
gap is 100% historical (522,215 / 661,633 rows, oldest timestamped row
2026-04-06).

This migration deliberately does NOT backfill the existing NULL rows and
does NOT add `NOT NULL`: there is no recoverable true timestamp for them
(no correlated column preserves it), and fabricating one -- `now()`, the
migration run time, or any other placeholder -- would silently corrupt
usage/cost history in a way nobody could later detect or distinguish from a
real timestamp. The NULL rows stay NULL and remain queryable as "unknown
timestamp"; `ALTER COLUMN ... SET NOT NULL` is intentionally deferred until/
unless a real backfill strategy is agreed.

What this migration DOES fix: `SET DEFAULT now()` on both columns, matching
the ORM model, so any writer that *omits* the column (raw SQL, a bulk
import, a different code path than the one above) can no longer land a
NULL row silently by omission. A writer that explicitly sets `created_at =
NULL` still can -- only `NOT NULL` closes that, and it is deliberately
deferred as explained above.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260804_1100"
down_revision = "20260803_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "usage_logs",
        "created_at",
        existing_type=sa.DateTime(),
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "usage_logs",
        "updated_at",
        existing_type=sa.DateTime(),
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "usage_logs",
        "created_at",
        existing_type=sa.DateTime(),
        server_default=None,
    )
    op.alter_column(
        "usage_logs",
        "updated_at",
        existing_type=sa.DateTime(),
        server_default=None,
    )
