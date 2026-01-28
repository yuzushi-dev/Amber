"""Add tenant_id to global_rules table

Revision ID: 20260128_1112
Revises: 20260128_0800
Create Date: 2026-01-28 11:12:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260128_1112'
down_revision = '20260128_0800'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add tenant_id column to global_rules table
    # Using nullable=True initially, then update existing rows
    op.add_column('global_rules', sa.Column('tenant_id', sa.String(), nullable=True))
    
    # Create index for tenant_id
    op.create_index('ix_global_rules_tenant_id', 'global_rules', ['tenant_id'], unique=False)
    
    # Note: After migration, run a data migration to populate tenant_id for existing rows
    # Then run: ALTER TABLE global_rules ALTER COLUMN tenant_id SET NOT NULL;


def downgrade() -> None:
    op.drop_index('ix_global_rules_tenant_id', table_name='global_rules')
    op.drop_column('global_rules', 'tenant_id')
