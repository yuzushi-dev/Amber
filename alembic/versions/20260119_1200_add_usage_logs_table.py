"""add usage_logs table

Revision ID: 20260119_1200
Revises: 20260116_1450
Create Date: 2026-01-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260119_1200'
down_revision = '20260116_1450'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('usage_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('request_id', sa.String(), nullable=True),
    sa.Column('trace_id', sa.String(), nullable=True),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('operation', sa.String(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('total_tokens', sa.Integer(), nullable=True),
    sa.Column('cost', sa.Float(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_logs_request_id'), 'usage_logs', ['request_id'], unique=False)
    op.create_index(op.f('ix_usage_logs_tenant_id'), 'usage_logs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_usage_logs_trace_id'), 'usage_logs', ['trace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_usage_logs_trace_id'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_tenant_id'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_request_id'), table_name='usage_logs')
    op.drop_table('usage_logs')
