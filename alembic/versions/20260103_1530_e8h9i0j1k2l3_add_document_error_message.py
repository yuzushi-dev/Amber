"""Add error_message to documents

Revision ID: e8h9i0j1k2l3
Revises: d7fg34e5g6h7
Create Date: 2026-01-03 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e8h9i0j1k2l3'
down_revision: Union[str, None] = 'd7fg34e5g6h7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('error_message', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'error_message')
