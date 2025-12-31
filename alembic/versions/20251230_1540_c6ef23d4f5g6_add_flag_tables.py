"""Add flags table

Revision ID: c6ef23d4f5g6
Revises: b5df12c3e4f5
Create Date: 2025-12-30 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c6ef23d4f5g6'
down_revision: Union[str, None] = 'b5df12c3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create flags table
    op.create_table(
        'flags',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('type', sa.Enum('wrong_fact', 'bad_link', 'wrong_entity', 'missing_entity', 'duplicate_entity', 'merge_suggestion', 'other', name='flagtype'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'accepted', 'rejected', 'merged', name='flagstatus'), nullable=False),
        sa.Column('reported_by', sa.String(), nullable=False),
        sa.Column('target_type', sa.String(), nullable=False),
        sa.Column('target_id', sa.String(), nullable=False),
        sa.Column('comment', sa.String(), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('resolved_by', sa.String(), nullable=True),
        sa.Column('resolved_at', sa.String(), nullable=True),
        sa.Column('resolution_notes', sa.String(), nullable=True),
        sa.Column('merge_target_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    
    # Create indexes
    op.create_index(op.f('ix_flags_tenant_id'), 'flags', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_flags_target_id'), 'flags', ['target_id'], unique=False)
    op.create_index(op.f('ix_flags_type'), 'flags', ['type'], unique=False)
    op.create_index(op.f('ix_flags_status'), 'flags', ['status'], unique=False)


def downgrade() -> None:
    # Drop table
    op.drop_index(op.f('ix_flags_status'), table_name='flags')
    op.drop_index(op.f('ix_flags_type'), table_name='flags')
    op.drop_index(op.f('ix_flags_target_id'), table_name='flags')
    op.drop_index(op.f('ix_flags_tenant_id'), table_name='flags')
    op.drop_table('flags')
    
    # Drop enums
    sa.Enum(name='flagstatus').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='flagtype').drop(op.get_bind(), checkfirst=False)
