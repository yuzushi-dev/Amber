"""add framework discriminator to benchmark_runs

Revision ID: 20260528_1100
Revises: 20260528_1000
Create Date: 2026-05-28 11:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260528_1100"
down_revision = "20260528_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "benchmark_runs",
        sa.Column("framework", sa.String(), server_default="ragas", nullable=False),
    )
    op.create_index(
        "ix_benchmark_runs_framework", "benchmark_runs", ["framework"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_benchmark_runs_framework", table_name="benchmark_runs")
    op.drop_column("benchmark_runs", "framework")
