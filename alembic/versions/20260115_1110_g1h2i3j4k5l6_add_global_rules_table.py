"""Add global_rules table

Revision ID: g1h2i3j4k5l6
Revises: a1b2c3d4e5f7
Create Date: 2026-01-15 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'global_rules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True, server_default='100'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('source', sa.String(), nullable=True, server_default="'manual'"),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_global_rules_category', 'global_rules', ['category'], unique=False)
    op.create_index('ix_global_rules_is_active', 'global_rules', ['is_active'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_global_rules_is_active', table_name='global_rules')
    op.drop_index('ix_global_rules_category', table_name='global_rules')
    op.drop_table('global_rules')
