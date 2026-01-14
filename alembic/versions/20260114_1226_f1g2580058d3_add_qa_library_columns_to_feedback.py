"""
add_qa_library_columns_to_feedback

Revision ID: f1g2580058d3
Revises: e0f3580058d2
Create Date: 2026-01-14 12:26:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f1g2580058d3'
down_revision: Union[str, None] = 'e0f3580058d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_active column for Q&A library control
    op.add_column('feedbacks', sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'))
    
    # Add query_embedding column for similarity search (stored as JSON array)
    op.add_column('feedbacks', sa.Column('query_embedding', sa.JSON(), nullable=True))
    
    # Make is_active non-nullable after setting default
    op.alter_column('feedbacks', 'is_active', nullable=False)


def downgrade() -> None:
    op.drop_column('feedbacks', 'query_embedding')
    op.drop_column('feedbacks', 'is_active')
