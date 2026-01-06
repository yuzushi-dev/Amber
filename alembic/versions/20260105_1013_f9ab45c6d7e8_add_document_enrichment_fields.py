"""add document enrichment fields

Revision ID: f9ab45c6d7e8
Revises: e8h9i0j1k2l3
Create Date: 2026-01-05 10:13:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'f9ab45c6d7e8'
down_revision = 'e8h9i0j1k2l3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add document enrichment fields
    op.add_column('documents', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('document_type', sa.String(), nullable=True))
    op.add_column('documents', sa.Column('keywords', JSONB(), server_default='[]', nullable=False))
    op.add_column('documents', sa.Column('hashtags', JSONB(), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('documents', 'hashtags')
    op.drop_column('documents', 'keywords')
    op.drop_column('documents', 'document_type')
    op.drop_column('documents', 'summary')
