"""add intra-tenant groups with selective document access RLS

Revision ID: 20260521_1000
Revises: 20260327_1900
Create Date: 2026-05-21 10:00:00.000000

Introduces intra-tenant groups (groups, group_members, group_folder_access,
group_document_access) with FORCE RLS tenant isolation. Adds an additive,
SECURITY DEFINER-backed read policy on documents that restricts visibility to
folders/documents granted to the caller's groups when group enforcement is on.
When app.groups_enforced='true', the base tenant_isolation policy no longer
grants blanket tenant access to non-admin callers.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260521_1000"
down_revision = "20260327_1900"
branch_labels = None
depends_on = None

GROUP_TABLES = [
    "groups",
    "group_members",
    "group_folder_access",
    "group_document_access",
]


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_groups_tenant_name"),
    )
    op.create_index("ix_groups_tenant_id", "groups", ["tenant_id"])

    op.create_table(
        "group_members",
        sa.Column(
            "group_id",
            sa.String(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "api_key_id",
            sa.String(),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), server_default="member", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_group_members_tenant_id", "group_members", ["tenant_id"])
    op.create_index("ix_group_members_api_key_id", "group_members", ["api_key_id"])

    op.create_table(
        "group_folder_access",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "folder_id",
            sa.String(),
            sa.ForeignKey("folders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access_mode", sa.String(), server_default="read", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "group_id", "folder_id", name="uq_group_folder_access_group_folder"
        ),
    )
    op.create_index(
        "ix_group_folder_access_tenant_id", "group_folder_access", ["tenant_id"]
    )
    op.create_index(
        "ix_group_folder_access_folder_id", "group_folder_access", ["folder_id"]
    )

    op.create_table(
        "group_document_access",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access_mode", sa.String(), server_default="read", nullable=False),
        sa.Column("is_deny", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "group_id", "document_id", name="uq_group_document_access_group_document"
        ),
    )
    op.create_index(
        "ix_group_document_access_tenant_id", "group_document_access", ["tenant_id"]
    )
    op.create_index(
        "ix_group_document_access_document_id", "group_document_access", ["document_id"]
    )

    # --- RLS: enable + FORCE + tenant isolation on every group table -----------
    for table in GROUP_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY tenant_isolation_{table}
                ON {table}
                FOR ALL
                USING (
                    tenant_id = current_setting('app.current_tenant', true)::text
                    OR current_setting('app.is_super_admin', true) = 'true'
                )
                WITH CHECK (
                    tenant_id = current_setting('app.current_tenant', true)::text
                    OR current_setting('app.is_super_admin', true) = 'true'
                )
                """
            )
        )

    # --- SECURITY DEFINER resolver (avoids RLS recursion on group tables) ------
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION app_visible_document_ids(p_tenant text, p_groups text[])
            RETURNS TABLE(document_id text)
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = public
            AS $$
                SELECT d.id
                FROM documents d
                WHERE d.tenant_id = p_tenant
                  AND (
                        EXISTS (
                            SELECT 1 FROM group_folder_access gfa
                            WHERE gfa.folder_id = d.folder_id
                              AND gfa.group_id = ANY(p_groups)
                              AND gfa.tenant_id = p_tenant
                        )
                     OR EXISTS (
                            SELECT 1 FROM group_document_access gda
                            WHERE gda.document_id = d.id
                              AND gda.group_id = ANY(p_groups)
                              AND gda.is_deny = FALSE
                              AND gda.tenant_id = p_tenant
                        )
                      )
                  AND NOT EXISTS (
                        SELECT 1 FROM group_document_access gda
                        WHERE gda.document_id = d.id
                          AND gda.group_id = ANY(p_groups)
                          AND gda.is_deny = TRUE
                          AND gda.tenant_id = p_tenant
                  );
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            "REVOKE ALL ON FUNCTION app_visible_document_ids(text, text[]) FROM PUBLIC"
        )
    )
    op.execute(
        sa.text(
            "GRANT EXECUTE ON FUNCTION app_visible_document_ids(text, text[]) TO graphrag_app"
        )
    )
    for tbl in ("groups", "group_members", "group_folder_access", "group_document_access"):
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO graphrag_app"))

    # --- Additive group read policy on documents ------------------------------
    op.execute(
        sa.text(
            """
            CREATE POLICY documents_group_read
            ON documents
            FOR SELECT
            USING (
                tenant_id = current_setting('app.current_tenant', true)::text
                AND current_setting('app.groups_enforced', true) = 'true'
                AND (current_setting('app.current_groups', true) IS NOT NULL
                     AND current_setting('app.current_groups', true) <> '')
                AND id IN (
                    SELECT document_id FROM app_visible_document_ids(
                        current_setting('app.current_tenant', true)::text,
                        string_to_array(current_setting('app.current_groups', true), ',')
                    )
                )
            )
            """
        )
    )

    # --- Remove orphan policy from 20260112_1223 that was never dropped -------
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_documents ON documents"))

    # --- Restrict base tenant_isolation under group enforcement ---------------
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON documents"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation
            ON documents
            USING (
                tenant_id = current_setting('app.current_tenant', true)::text
                AND (
                    current_setting('app.is_super_admin', true) = 'true'
                    OR current_setting('app.tenant_role', true) = 'admin'
                    OR current_setting('app.groups_enforced', true) IS DISTINCT FROM 'true'
                )
            )
            """
        )
    )

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_chunks ON chunks"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_chunks
            ON chunks
            USING (
                tenant_id = current_setting('app.current_tenant', true)::text
                AND (
                    current_setting('app.is_super_admin', true) = 'true'
                    OR current_setting('app.tenant_role', true) = 'admin'
                    OR current_setting('app.groups_enforced', true) IS DISTINCT FROM 'true'
                )
            )
            """
        )
    )


def downgrade() -> None:
    # --- Restore base tenant_isolation policies (super_admin RLS variant) ------
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_chunks ON chunks"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation_chunks
            ON chunks
            USING (
                tenant_id = current_setting('app.current_tenant', true)::text
                OR current_setting('app.is_super_admin', true) = 'true'
            )
            """
        )
    )

    op.execute(sa.text("DROP POLICY IF EXISTS documents_group_read ON documents"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON documents"))
    op.execute(
        sa.text(
            """
            CREATE POLICY tenant_isolation
            ON documents
            USING (
                tenant_id = current_setting('app.current_tenant', true)::text
                OR current_setting('app.is_super_admin', true) = 'true'
            )
            """
        )
    )

    # --- Drop resolver function -----------------------------------------------
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS app_visible_document_ids(text, text[])")
    )

    # --- Drop group-table policies + tables (reverse order) -------------------
    for table in reversed(GROUP_TABLES):
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    op.drop_index(
        "ix_group_document_access_document_id", table_name="group_document_access"
    )
    op.drop_index(
        "ix_group_document_access_tenant_id", table_name="group_document_access"
    )
    op.drop_table("group_document_access")

    op.drop_index("ix_group_folder_access_folder_id", table_name="group_folder_access")
    op.drop_index("ix_group_folder_access_tenant_id", table_name="group_folder_access")
    op.drop_table("group_folder_access")

    op.drop_index("ix_group_members_api_key_id", table_name="group_members")
    op.drop_index("ix_group_members_tenant_id", table_name="group_members")
    op.drop_table("group_members")

    op.drop_index("ix_groups_tenant_id", table_name="groups")
    op.drop_table("groups")
