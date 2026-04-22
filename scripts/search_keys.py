import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import or_, select

from src.api.deps import _async_session_maker
from src.core.models.api_key import ApiKey


async def search_keys():
    async with _async_session_maker() as session:
        # Import models inside to ensure they are registered
        query = select(ApiKey).where(or_(
            ApiKey.name.ilike("%dev%"),
            ApiKey.name.ilike("%amber%"),
            ApiKey.prefix.ilike("%dev%"),
            ApiKey.prefix.ilike("%amber%")
        ))
        result = await session.execute(query)
        keys = result.scalars().all()
        if not keys:
            print("No matching keys found.")
            # List all keys again just to be super sure
            result = await session.execute(select(ApiKey))
            keys = result.scalars().all()

        for k in keys:
            print(f"ID: {k.id} | Name: {k.name} | Prefix: {k.prefix} | Scopes: {k.scopes}")

if __name__ == "__main__":
    asyncio.run(search_keys())
