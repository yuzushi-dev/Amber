"""Add source tracking and connector state

Revision ID: b5df12c3e4f5
Revises: a4bfb860998e
Create Date: 2024-12-30 09:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b5df12c3e4f5'
down_revision: str | None = 'a4bfb860998e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add source tracking columns to documents table
    op.add_column('documents', sa.Column('source_type', sa.String(), nullable=False, server_default='file'))
    op.add_column('documents', sa.Column('source_url', sa.String(), nullable=True))

    # Create connector_states table
    op.create_table(
        'connector_states',
        sa.Column('id', sa.String(), primary_key=True, index=True),
        sa.Column('tenant_id', sa.String(), nullable=False, index=True),
        sa.Column('connector_type', sa.String(), nullable=False),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_cursor', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='idle'),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    # Drop connector_states table
    op.drop_table('connector_states')

    # Remove source tracking columns from documents
    op.drop_column('documents', 'source_url')
    op.drop_column('documents', 'source_type')
