"""Seed intra-tenant groups and folder access for the local 'default' tenant.

Uses raw SQL to avoid SQLAlchemy mapper resolution issues with cross-model FKs.

Groups created:
    PE        -> AdminGuide, CEGuide, UserGuide, ZendeskKB
    Sales     -> Sales, partner HB, ZendeskKB
    Marketing -> every folder in the tenant
"""

import asyncio
import os
import sys
from uuid import uuid4

sys.path.append(os.getcwd())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

TENANT_ID = "default"

GROUP_FOLDER_MAPPING: dict[str, list[str]] = {
    "PE": ["AdminGuide", "CEGuide", "UserGuide", "ZendeskKB"],
    "Sales": ["Sales", "partner HB", "ZendeskKB"],
}

GROUP_DESCRIPTIONS = {
    "PE": "Product Engineering: admin/CE/user guides + Zendesk KB",
    "Sales": "Sales: sales material, partner HB + Zendesk KB",
    "Marketing": "Marketing: full visibility over all folders",
}


async def main() -> None:
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag",
    )
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Bypass FORCE RLS for seed inserts
        await session.execute(text("SELECT set_config('app.is_super_admin', 'true', false)"))
        await session.execute(text("SELECT set_config('app.current_tenant', :tid, false)"), {"tid": TENANT_ID})

        # Fetch folders
        result = await session.execute(
            text("SELECT id, name FROM folders WHERE tenant_id = :tid ORDER BY name"),
            {"tid": TENANT_ID},
        )
        folders = {row.name: row.id for row in result.fetchall()}

        if not folders:
            print(f"No folders found for tenant '{TENANT_ID}'.")
            print("Import prod DB first or run with real data.")
            await engine.dispose()
            return

        print(f"Found {len(folders)} folders: {', '.join(sorted(folders))}")

        summary: dict[str, list[str]] = {}

        for group_name in ("PE", "Sales", "Marketing"):
            # Get or create group
            existing = await session.execute(
                text("SELECT id FROM groups WHERE tenant_id = :tid AND name = :name"),
                {"tid": TENANT_ID, "name": group_name},
            )
            row = existing.fetchone()
            if row:
                group_id = row[0]
                print(f"{group_name}: group already exists ({group_id})")
            else:
                group_id = str(uuid4())
                await session.execute(
                    text("""
                        INSERT INTO groups (id, tenant_id, name, description, is_active, created_at, updated_at)
                        VALUES (:id, :tid, :name, :desc, true, now(), now())
                    """),
                    {"id": group_id, "tid": TENANT_ID, "name": group_name, "desc": GROUP_DESCRIPTIONS.get(group_name)},
                )
                print(f"{group_name}: created group ({group_id})")

            # Determine target folders
            if group_name == "Marketing":
                wanted = list(folders.keys())
            else:
                wanted = GROUP_FOLDER_MAPPING[group_name]

            granted: list[str] = []
            for fname in wanted:
                folder_id = folders.get(fname)
                if not folder_id:
                    print(f"  [warn] folder '{fname}' not found")
                    continue

                # Check existing grant
                exists = await session.execute(
                    text("SELECT 1 FROM group_folder_access WHERE group_id = :gid AND folder_id = :fid"),
                    {"gid": group_id, "fid": folder_id},
                )
                if exists.fetchone():
                    continue

                await session.execute(
                    text("""
                        INSERT INTO group_folder_access (id, group_id, folder_id, tenant_id, access_mode, created_at)
                        VALUES (:id, :gid, :fid, :tid, 'read', now())
                    """),
                    {"id": str(uuid4()), "gid": group_id, "fid": folder_id, "tid": TENANT_ID},
                )
                granted.append(fname)

            summary[group_name] = granted

        await session.commit()

    print("\n=== Seed summary (tenant 'default') ===")
    for group_name in ("PE", "Sales", "Marketing"):
        granted = summary.get(group_name, [])
        if granted:
            print(f"  {group_name}: granted -> {', '.join(granted)}")
        else:
            print(f"  {group_name}: no new grants (already present or folders missing)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
