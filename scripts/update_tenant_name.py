import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import select

from src.core.database.session import async_session_maker
from src.core.models.tenant import Tenant


async def main():
    try:
        async with async_session_maker() as session:
            # Check if default tenant exists
            result = await session.execute(select(Tenant).where(Tenant.id == 'default'))
            tenant = result.scalar_one_or_none()

            if tenant:
                print(f"Updating tenant 'default' name from '{tenant.name}' to 'Global Admin'...")
                tenant.name = 'Global Admin'
                session.add(tenant)
                await session.commit()
                print("Tenant 'default' updated successfully.")
            else:
                print("Tenant 'default' not found. Cannot update.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
