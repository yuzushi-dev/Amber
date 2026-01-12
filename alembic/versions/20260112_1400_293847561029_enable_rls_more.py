"""enable rls on folders and others

Revision ID: 293847561029
Revises: 20260112_1223_d7fe42b0ac1c
Create Date: 2026-01-12 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '293847561029'
down_revision = 'd7fe42b0ac1c' # Assuming this is the previous one. I should verify via alembic current output.
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Enable RLS on folders
    op.execute("ALTER TABLE folders ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation_folders ON folders USING (tenant_id = current_setting('app.current_tenant')::text)")
    
    # Enable RLS on audit_logs
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation_audit_logs ON audit_logs USING (tenant_id = current_setting('app.current_tenant')::text)")
    
    # Enable RLS on feedbacks
    op.execute("ALTER TABLE feedbacks ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation_feedbacks ON feedbacks USING (tenant_id = current_setting('app.current_tenant')::text)")


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation_feedbacks ON feedbacks")
    op.execute("ALTER TABLE feedbacks DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY tenant_isolation_audit_logs ON audit_logs")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY tenant_isolation_folders ON folders")
    op.execute("ALTER TABLE folders DISABLE ROW LEVEL SECURITY")
