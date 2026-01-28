"""Add backup and restore tables

Revision ID: 20260128_0800
Revises: 20260121_1237
Create Date: 2026-01-28 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260128_0800'
down_revision = '20260121_1237'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create backup_jobs table
    op.create_table(
        'backup_jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('scope', sa.Enum('user_data', 'full_system', name='backupscope'), nullable=False, server_default='user_data'),
        sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', 'cancelled', name='backupstatus'), nullable=False, server_default='pending'),
        sa.Column('result_path', sa.String(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('is_scheduled', sa.String(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_backup_jobs_tenant_id'), 'backup_jobs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_backup_jobs_user_id'), 'backup_jobs', ['user_id'], unique=False)

    # Create restore_jobs table
    op.create_table(
        'restore_jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('backup_job_id', sa.String(), nullable=True),
        sa.Column('upload_path', sa.String(), nullable=True),
        sa.Column('mode', sa.Enum('merge', 'replace', name='restoremode'), nullable=False, server_default='merge'),
        sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', 'cancelled', name='backupstatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('items_restored', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_restore_jobs_tenant_id'), 'restore_jobs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_restore_jobs_user_id'), 'restore_jobs', ['user_id'], unique=False)

    # Create backup_schedules table
    op.create_table(
        'backup_schedules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('enabled', sa.String(), nullable=False, server_default='false'),
        sa.Column('frequency', sa.String(), nullable=False, server_default='daily'),
        sa.Column('time_utc', sa.String(), nullable=False, server_default='02:00'),
        sa.Column('day_of_week', sa.Integer(), nullable=True),
        sa.Column('scope', sa.Enum('user_data', 'full_system', name='backupscope', create_type=False), nullable=False, server_default='user_data'),
        sa.Column('retention_count', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id')
    )
    op.create_index(op.f('ix_backup_schedules_tenant_id'), 'backup_schedules', ['tenant_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_backup_schedules_tenant_id'), table_name='backup_schedules')
    op.drop_table('backup_schedules')
    
    op.drop_index(op.f('ix_restore_jobs_user_id'), table_name='restore_jobs')
    op.drop_index(op.f('ix_restore_jobs_tenant_id'), table_name='restore_jobs')
    op.drop_table('restore_jobs')
    
    op.drop_index(op.f('ix_backup_jobs_user_id'), table_name='backup_jobs')
    op.drop_index(op.f('ix_backup_jobs_tenant_id'), table_name='backup_jobs')
    op.drop_table('backup_jobs')
    
    # Drop enum types
    op.execute('DROP TYPE IF EXISTS restoremode')
    op.execute('DROP TYPE IF EXISTS backupstatus')
    op.execute('DROP TYPE IF EXISTS backupscope')
