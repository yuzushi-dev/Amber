"""Add graphrag_app role, RLS policies on remaining tenant tables, and FORCE RLS

Revision ID: 20260325_1600
Revises: 20260325_1500
Create Date: 2026-03-25 16:00:00.000000

Creates a non-owner, non-superuser application role (graphrag_app) so that
the app never bypasses RLS.  Adds missing tenant-isolation RLS policies and
enables FORCE ROW LEVEL SECURITY on tables where RLS was previously advisory.
"""

import os

import sqlalchemy as sa

from alembic import op

revision = '20260325_1600'
down_revision = '20260325_1500'
branch_labels = None
depends_on = None

# Tables that already have RLS enabled — enable FORCE to make it apply to the
# owner role too (belt-and-suspenders; the non-owner app role already respects
# regular RLS without FORCE).
FORCE_RLS_TABLES = [
    "documents",
    "chunks",
    "feedbacks",
    "folders",
    "audit_logs",
]

# Tables that need RLS enabled + new policies (they have tenant_id columns)
NEW_RLS_TABLES = [
    "connector_states",
    "conversation_summaries",
    "graph_edit_history",
]


def upgrade() -> None:
    password = os.environ.get("GRAPHRAG_APP_PASSWORD")
    if not password:
        raise RuntimeError(
            "GRAPHRAG_APP_PASSWORD env var is required to run this migration. "
            "Set it in .env and re-run."
        )

    # --- 1. Create application role ----------------------------------------
    op.execute(sa.text(
        "CREATE ROLE graphrag_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOINHERIT NOREPLICATION NOBYPASSRLS "
        f"PASSWORD '{password}'"
    ))

    # --- 2. Grant table privileges ------------------------------------------
    # SELECT, INSERT, UPDATE, DELETE on all current public tables
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO graphrag_app"
    ))
    # Allow using sequences (needed for INSERT with serial columns)
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO graphrag_app"
    ))
    # Allow CONNECT to the database
    op.execute(sa.text("GRANT CONNECT ON DATABASE graphrag TO graphrag_app"))
    # Allow USAGE on the public schema
    op.execute(sa.text("GRANT USAGE ON SCHEMA public TO graphrag_app"))

    # --- 3. Ensure future tables/sequences are also accessible -------------
    op.execute(sa.text(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO graphrag_app"
    ))
    op.execute(sa.text(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO graphrag_app"
    ))

    # --- 4. Add RLS policies for tables not yet covered --------------------
    for table in NEW_RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "FOR ALL "
            "USING ( "
            "  tenant_id = current_setting('app.current_tenant', true) "
            "  OR current_setting('app.is_super_admin', true) = 'true' "
            ")"
        ))

    # --- 5. Enable FORCE RLS on existing tenant-scoped tables --------------
    for table in FORCE_RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    # --- 6. Enable FORCE RLS on newly-covered tables too -------------------
    for table in NEW_RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def downgrade() -> None:
    # --- 6 rev. Remove FORCE RLS from new tables ---------------------------
    for table in NEW_RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))

    # --- 5 rev. Remove FORCE RLS from existing tables ----------------------
    for table in FORCE_RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))

    # --- 4 rev. Drop new policies and disable RLS --------------------------
    for table in NEW_RLS_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    # --- 2-3 rev. Revoke grants --------------------------------------------
    op.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM graphrag_app"))
    op.execute(sa.text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM graphrag_app"))
    op.execute(sa.text("REVOKE CONNECT ON DATABASE graphrag FROM graphrag_app"))
    op.execute(sa.text("REVOKE USAGE ON SCHEMA public FROM graphrag_app"))

    # --- 1 rev. Drop role --------------------------------------------------
    op.execute(sa.text("DROP ROLE IF EXISTS graphrag_app"))
