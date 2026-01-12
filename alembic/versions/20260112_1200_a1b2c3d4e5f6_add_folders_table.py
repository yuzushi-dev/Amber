"""add_folders_table

Revision ID: a1b2c3d4e5f6
Revises: f40c9184d431
Create Date: 2026-01-12 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f40c9184d431'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create folders table
    op.create_table('folders',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_folders_id'), 'folders', ['id'], unique=False)
    op.create_index(op.f('ix_folders_tenant_id'), 'folders', ['tenant_id'], unique=False)

    # Add folder_id to documents
    op.add_column('documents', sa.Column('folder_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_documents_folder_id'), 'documents', ['folder_id'], unique=False)
    op.create_foreign_key(None, 'documents', 'folders', ['folder_id'], ['id'])


def downgrade() -> None:
    # Drop folder_id from documents
    op.drop_constraint(None, 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_documents_folder_id'), table_name='documents')
    op.drop_column('documents', 'folder_id')

    # Drop folders table
    op.drop_index(op.f('ix_folders_tenant_id'), table_name='folders')
    op.drop_index(op.f('ix_folders_id'), table_name='folders')
    op.drop_table('folders')
