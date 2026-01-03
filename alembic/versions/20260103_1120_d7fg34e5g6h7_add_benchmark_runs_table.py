"""Add benchmark_runs table

Revision ID: d7fg34e5g6h7
Revises: c6ef23d4f5g6
Create Date: 2026-01-03 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd7fg34e5g6h7'
down_revision: Union[str, None] = 'c6ef23d4f5g6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create benchmark_status enum
    benchmark_status = sa.Enum('pending', 'running', 'completed', 'failed', name='benchmarkstatus')
    benchmark_status.create(op.get_bind(), checkfirst=True)
    
    # Create benchmark_runs table
    op.create_table(
        'benchmark_runs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('dataset_name', sa.String(), nullable=False),
        sa.Column('status', benchmark_status, nullable=False, server_default='pending'),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    
    # Create indexes
    op.create_index(op.f('ix_benchmark_runs_tenant_id'), 'benchmark_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_benchmark_runs_status'), 'benchmark_runs', ['status'], unique=False)


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_benchmark_runs_status'), table_name='benchmark_runs')
    op.drop_index(op.f('ix_benchmark_runs_tenant_id'), table_name='benchmark_runs')
    
    # Drop table
    op.drop_table('benchmark_runs')
    
    # Drop enum
    sa.Enum(name='benchmarkstatus').drop(op.get_bind(), checkfirst=False)
