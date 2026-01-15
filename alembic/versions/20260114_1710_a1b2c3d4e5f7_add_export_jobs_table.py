"""Add export_jobs table

Revision ID: a1b2c3d4e5f7
Revises: f1g2580058d3
Create Date: 2026-01-14 17:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = 'f1g2580058d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create export_jobs table
    op.create_table(
        'export_jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', name='exportstatus'), nullable=False, server_default='pending'),
        sa.Column('result_path', sa.String(), nullable=True),
        sa.Column('file_size', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_export_jobs_tenant_id'), 'export_jobs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_export_jobs_user_id'), 'export_jobs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_export_jobs_user_id'), table_name='export_jobs')
    op.drop_index(op.f('ix_export_jobs_tenant_id'), table_name='export_jobs')
    op.drop_table('export_jobs')
    
    # Drop the enum type
    op.execute('DROP TYPE IF EXISTS exportstatus')
