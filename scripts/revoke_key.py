import asyncio
import os
import sys

# Add src to pythonpath
sys.path.append(os.getcwd())

from src.api.deps import _async_session_maker
from src.core.services.api_key_service import ApiKeyService


async def main():
    try:
        async with _async_session_maker() as session:
            service = ApiKeyService(session)

            # List active keys first
            keys = await service.list_keys()
            if not keys:
                print("No active API keys found.")
                return

            print(f"\nFound {len(keys)} active keys:")
            print(f"{'ID':<36} | {'Name':<20} | {'Prefix':<10} | {'Created At'}")
            print("-" * 90)

            for key in keys:
                created_at = key.created_at.strftime("%Y-%m-%d %H:%M") if key.created_at else "N/A"
                print(f"{key.id:<36} | {key.name:<20} | {key.prefix:<10} | {created_at}")

            print("\n")
            key_id = input("Enter the ID of the key to revoke (or 'q' to quit): ").strip()

            if key_id.lower() == 'q':
                return

            if not any(str(k.id) == key_id for k in keys):
                print("Invalid Key ID.")
                return

            confirm = input(f"Are you sure you want to revoke key {key_id}? (y/N): ").strip().lower()
            if confirm == 'y':
                success = await service.revoke_key(key_id)
                if success:
                    print(f"Successfully revoked key {key_id}")
                else:
                    print(f"Failed to revoke key {key_id}")
            else:
                print("Operation cancelled.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
