"""add missing document statuses

Revision ID: 20260116_1450
Revises: g1h2i3j4k5l6
Create Date: 2026-01-16 14:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260116_1450'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'EMBEDDING' to documentstatus enum
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'EMBEDDING'")
    # Add 'GRAPH_SYNC' to documentstatus enum
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'GRAPH_SYNC'")


def downgrade() -> None:
    # Downgrade is not supported for enum modification in postgres
    pass
