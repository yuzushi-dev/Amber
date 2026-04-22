import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import select

from src.api.deps import _async_session_maker
from src.core.models.api_key import ApiKey


async def list_keys():
    async with _async_session_maker() as session:
        result = await session.execute(select(ApiKey))
        keys = result.scalars().all()
        for k in keys:
            print(f"ID: {k.id} | Name: {k.name} | Prefix: {k.prefix} | Scopes: {k.scopes}")

if __name__ == "__main__":
    asyncio.run(list_keys())
