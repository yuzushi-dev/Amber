import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import select

from src.api.config import settings
from src.core.database.session import async_session_maker, configure_database
from src.core.tenants.domain.tenant import Tenant
from src.core.tenants.application.llm_model_backfill import backfill_llm_model_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill llm_model/generation_model in tenant config")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing to DB")
    return parser.parse_args()


async def main(dry_run: bool) -> None:
    configure_database(
        settings.db.database_url,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow,
    )

    async with async_session_maker() as session:
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()

        updated = 0
        for tenant in tenants:
            config = tenant.config or {}
            new_config, changed = backfill_llm_model_config(config)
            if changed:
                updated += 1
                if not dry_run:
                    tenant.config = new_config
                    session.add(tenant)

        if dry_run:
            print(f"Dry run: {updated}/{len(tenants)} tenants would be updated.")
            return

        await session.commit()
        print(f"Updated {updated}/{len(tenants)} tenants.")


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args.dry_run))
