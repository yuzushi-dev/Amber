"""Add chunks_group_read RLS policy for group-based chunk visibility

Revision ID: 20260603_1300
Revises: 20260603_1200
Create Date: 2026-06-03 13:00:00.000000

Under groups_enforced=true the base tenant_isolation_chunks policy (added by
20260521_1000_add_groups.py) restricts chunk reads to admins and super-admins
only, with no additive policy to re-grant access to group members.  This means
that even if a user's group has folder/document access (and can therefore read
the parent document via documents_group_read), the matching chunks are silently
invisible.  chunk reads therefore returned empty results for normal group members
when enforcement was on.

This migration adds a chunks_group_read policy that mirrors documents_group_read
exactly:

  * Same tenant_id guard.
  * Same groups_enforced='true' guard.
  * Same non-empty current_groups guard.
  * Visibility predicate: chunk.document_id IN app_visible_document_ids(...)
    — the existing SECURITY DEFINER helper that already powers documents_group_read.

The SECURITY DEFINER function app_visible_document_ids already exists and has
EXECUTE granted to graphrag_app (see 20260521_1000).

downgrade() drops the policy, restoring the pre-fix state (chunks remain
inaccessible to group members under groups_enforced=true — the pre-existing gap).
"""

import sqlalchemy as sa

from alembic import op

revision = "20260603_1300"
down_revision = "20260603_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE POLICY chunks_group_read
            ON chunks
            FOR SELECT
            USING (
                tenant_id = current_setting('app.current_tenant', true)::text
                AND current_setting('app.groups_enforced', true) = 'true'
                AND (current_setting('app.current_groups', true) IS NOT NULL
                     AND current_setting('app.current_groups', true) <> '')
                AND document_id IN (
                    SELECT document_id FROM app_visible_document_ids(
                        current_setting('app.current_tenant', true)::text,
                        string_to_array(current_setting('app.current_groups', true), ',')
                    )
                )
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS chunks_group_read ON chunks"))
