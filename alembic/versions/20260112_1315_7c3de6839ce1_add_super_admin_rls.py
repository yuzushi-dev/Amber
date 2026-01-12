"""
add_super_admin_rls

Revision ID: 7c3de6839ce1
Revises: 293847561029
Create Date: 2026-01-12 13:15:30.203290
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7c3de6839ce1'
down_revision: Union[str, None] = '293847561029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Documents
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON documents")
    op.execute("""
        CREATE POLICY tenant_isolation ON documents 
        USING (tenant_id = current_setting('app.current_tenant', true)::text 
            OR current_setting('app.is_super_admin', true) = 'true')
    """)

    # 2. Chunks
    op.execute("DROP POLICY IF EXISTS tenant_isolation_chunks ON chunks")
    op.execute("""
        CREATE POLICY tenant_isolation_chunks ON chunks 
        USING (tenant_id = current_setting('app.current_tenant', true)::text 
            OR current_setting('app.is_super_admin', true) = 'true')
    """)

    # 3. Folders
    op.execute("DROP POLICY IF EXISTS tenant_isolation_folders ON folders")
    op.execute("""
        CREATE POLICY tenant_isolation_folders ON folders 
        USING (tenant_id = current_setting('app.current_tenant', true)::text 
            OR current_setting('app.is_super_admin', true) = 'true')
    """)

    # 4. Audit Logs
    op.execute("DROP POLICY IF EXISTS tenant_isolation_audit_logs ON audit_logs")
    op.execute("""
        CREATE POLICY tenant_isolation_audit_logs ON audit_logs 
        USING (tenant_id = current_setting('app.current_tenant', true)::text 
            OR current_setting('app.is_super_admin', true) = 'true')
    """)

    # 5. Feedbacks
    op.execute("DROP POLICY IF EXISTS tenant_isolation_feedbacks ON feedbacks")
    op.execute("""
        CREATE POLICY tenant_isolation_feedbacks ON feedbacks 
        USING (tenant_id = current_setting('app.current_tenant', true)::text 
            OR current_setting('app.is_super_admin', true) = 'true')
    """)


def downgrade() -> None:
    # Revert to strict tenant isolation
    
    # 1. Documents
    op.execute("DROP POLICY tenant_isolation ON documents")
    op.execute("CREATE POLICY tenant_isolation ON documents USING (tenant_id = current_setting('app.current_tenant')::text)")
    
    # 2. Chunks
    op.execute("DROP POLICY tenant_isolation_chunks ON chunks")
    op.execute("CREATE POLICY tenant_isolation_chunks ON chunks USING (tenant_id = current_setting('app.current_tenant')::text)")

    # 3. Folders
    op.execute("DROP POLICY tenant_isolation_folders ON folders")
    op.execute("CREATE POLICY tenant_isolation_folders ON folders USING (tenant_id = current_setting('app.current_tenant')::text)")
    
    # 4. Audit Logs
    op.execute("DROP POLICY tenant_isolation_audit_logs ON audit_logs")
    op.execute("CREATE POLICY tenant_isolation_audit_logs ON audit_logs USING (tenant_id = current_setting('app.current_tenant')::text)")
    
    # 5. Feedbacks
    op.execute("DROP POLICY tenant_isolation_feedbacks ON feedbacks")
    op.execute("CREATE POLICY tenant_isolation_feedbacks ON feedbacks USING (tenant_id = current_setting('app.current_tenant')::text)")
