"""Fix usage_logs.created_at: set DEFAULT now() and backfill NULLs from updated_at.

Usage:
    # Dry run (default)
    python scripts/fix_usage_logs_created_at.py

    # Apply
    python scripts/fix_usage_logs_created_at.py --execute

    # Against prod via SSH tunnel (DB on localhost:5433)
    DATABASE_URL=postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag \\
        python scripts/fix_usage_logs_created_at.py --execute
"""

import argparse
import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def main(execute: bool) -> None:
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag",
    )
    engine = create_async_engine(db_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Diagnostics
        total = (await session.execute(text("SELECT count(*) FROM usage_logs"))).scalar()
        null_count = (await session.execute(
            text("SELECT count(*) FROM usage_logs WHERE created_at IS NULL")
        )).scalar()
        has_default = (await session.execute(text("""
            SELECT column_default
            FROM information_schema.columns
            WHERE table_name = 'usage_logs' AND column_name = 'created_at'
        """))).scalar()

        print(f"\nusage_logs diagnostics:")
        print(f"  Total rows       : {total:,}")
        print(f"  NULL created_at  : {null_count:,}")
        print(f"  Current default  : {has_default or '(none)'}")

        if null_count == 0 and has_default:
            print("\nNothing to do — created_at already populated and default set.")
            await engine.dispose()
            return

        prefix = "" if execute else "[DRY RUN] "

        if not has_default:
            print(f"\n{prefix}ALTER TABLE usage_logs ALTER COLUMN created_at SET DEFAULT now()")
        if null_count > 0:
            print(f"{prefix}UPDATE usage_logs SET created_at = updated_at WHERE created_at IS NULL")
            print(f"  → {null_count:,} rows would be backfilled using updated_at")

        if not execute:
            print("\nRe-run with --execute to apply.")
            await engine.dispose()
            return

        if not has_default:
            await session.execute(text(
                "ALTER TABLE usage_logs ALTER COLUMN created_at SET DEFAULT now()"
            ))
            print("Default set.")

        if null_count > 0:
            result = await session.execute(text(
                "UPDATE usage_logs SET created_at = updated_at WHERE created_at IS NULL"
            ))
            print(f"Backfilled {result.rowcount:,} rows.")

        await session.commit()
        print("\nDone.")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.execute))
