import asyncio
import os
import sys

# Add src to pythonpath
sys.path.append(os.getcwd())

from src.api.deps import _async_session_maker
from src.core.admin_ops.application.api_key_service import ApiKeyService


async def main():
    try:
        async with _async_session_maker() as session:
            service = ApiKeyService(session)
            # Create a key with admin scope
            result = await service.create_key(name="temp-admin-key", scopes=["admin", "active_user"])
            print(f"raw_api_key={result['key']}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
