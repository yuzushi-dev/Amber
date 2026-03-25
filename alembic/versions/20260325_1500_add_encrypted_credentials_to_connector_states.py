"""Add encrypted_credentials to connector_states

Revision ID: 20260325_1500
Revises: 20260128_1112
Create Date: 2026-03-25 15:00:00.000000

Moves raw OAuth/API credentials out of the sync_cursor JSONB (plaintext)
into a dedicated encrypted_credentials TEXT column.  The application layer
encrypts with Fernet before storing and decrypts on read.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260325_1500'
down_revision = '20260128_1112'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'connector_states',
        sa.Column('encrypted_credentials', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('connector_states', 'encrypted_credentials')
