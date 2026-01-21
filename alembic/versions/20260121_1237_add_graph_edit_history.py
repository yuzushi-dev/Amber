"""add graph_edit_history table

Revision ID: 20260121_1237
Revises: 20260119_1200
Create Date: 2026-01-21 12:37:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260121_1237'
down_revision = '20260119_1200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('graph_edit_history',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('action_type', sa.String(), nullable=False),  # connect, merge, prune, heal, delete_edge, delete_node
    sa.Column('status', sa.String(), nullable=False),  # pending, applied, rejected, undone
    sa.Column('payload', sa.JSON(), nullable=False),  # Full request payload for replay
    sa.Column('snapshot', sa.JSON(), nullable=True),  # Pre-action state snapshot for undo
    sa.Column('source_view', sa.String(), nullable=True),  # 'global' or 'document:{doc_id}'
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=True),
    sa.Column('applied_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_graph_edit_history_tenant_id'), 'graph_edit_history', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_graph_edit_history_status'), 'graph_edit_history', ['status'], unique=False)
    op.create_index('ix_graph_edit_history_tenant_status_created', 'graph_edit_history', ['tenant_id', 'status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_graph_edit_history_tenant_status_created', table_name='graph_edit_history')
    op.drop_index(op.f('ix_graph_edit_history_status'), table_name='graph_edit_history')
    op.drop_index(op.f('ix_graph_edit_history_tenant_id'), table_name='graph_edit_history')
    op.drop_table('graph_edit_history')
