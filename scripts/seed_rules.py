
import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from sqlalchemy import delete

from src.api.config import settings as api_settings
from src.core.admin_ops.domain.global_rule import GlobalRule
from src.core.database.session import async_session_maker, configure_database
from src.shared.kernel.runtime import configure_settings


async def main():
    # Initialize settings and database
    configure_settings(api_settings)
    configure_database(
        database_url=api_settings.db.database_url,
        pool_size=api_settings.db.pool_size,
        max_overflow=api_settings.db.max_overflow
    )

    async with async_session_maker() as session:
        # Clear existing rules (if any)
        await session.execute(delete(GlobalRule))

        # Add rules
        rules = [
            GlobalRule(
                content="Unless specified otherwise, assume the user is asking about Carbonio CE (Community Edition).",
                priority=1,
                is_active=True
            ),
            GlobalRule(
                content="Prioritize 'CE' documentation over generic 'Carbonio' documentation when both are relevant, unless the commercial edition is explicitly mentioned.",
                priority=2,
                is_active=True
            ),
            GlobalRule(
                content="For end-user tasks like webmail usage, searching in folders, or junk mail management, prioritize the 'User Guide' (USER) documentation.",
                priority=3,
                is_active=True
            )
        ]
        session.add_all(rules)
        await session.commit()
        print("Rules seeded successfully.")

if __name__ == "__main__":
    asyncio.run(main())
