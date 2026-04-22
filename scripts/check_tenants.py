import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

# Ensure models are imported to register with SQLAlchemy
from sqlalchemy import select

from src.core.database.session import async_session_maker
from src.core.models.tenant import Tenant


async def main():
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(Tenant))
            tenants = result.scalars().all()
            print(f"Found {len(tenants)} tenants:")
            for t in tenants:
                print(f"ID: {t.id}, Name: {t.name}, API Key Prefix: {t.api_key_prefix}")

            if not tenants:
                print("No tenants found.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
