import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import select, update

from src.api.deps import _async_session_maker
from src.core.models.api_key import ApiKey


async def update_key():
    async with _async_session_maker() as session:
        # 1. Update Development Key
        query = select(ApiKey).where(ApiKey.name == "Development Key")
        result = await session.execute(query)
        key_record = result.scalars().first()

        if key_record:
            # Add super_admin if not present
            current_scopes = list(key_record.scopes) if key_record.scopes else []
            if "super_admin" not in current_scopes:
                current_scopes.append("super_admin")

            # Use update statement to ensure persistence
            stmt = update(ApiKey).where(ApiKey.id == key_record.id).values(scopes=current_scopes)
            await session.execute(stmt)
            await session.commit()
            print(f"Updated 'Development Key' with scopes: {current_scopes}")
        else:
            print("ERROR: Development Key not found.")

if __name__ == "__main__":
    asyncio.run(update_key())
