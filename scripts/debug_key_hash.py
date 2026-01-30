import asyncio
import sys
import os
from sqlalchemy import select

# Add src to pythonpath
sys.path.append(os.getcwd())

from src.api.deps import _get_async_session_maker
from src.core.admin_ops.domain.api_key import ApiKey
from src.core.tenants.domain.tenant import Tenant
from src.shared.security import hash_api_key, configure_security
from src.api.config import settings
from src.core.database.session import configure_database

async def main():
    try:
        # 0. Configure DB
        print(f"DEBUG: Configuring DB: {settings.db.database_url.split('@')[-1]}")
        configure_database(
            database_url=settings.db.database_url,
            pool_size=settings.db.pool_size,
            max_overflow=settings.db.max_overflow,
        )

        # 0.5 Configure Security (Crucial for correct hashing)
        print(f"DEBUG: Configuring Security with Secret Key: {settings.secret_key[:5]}...")
        configure_security(settings.secret_key)

        # 1. Print current settings
        print(f"DEBUG: SECRET_KEY loaded = {settings.secret_key[:5]}...{settings.secret_key[-5:]}")
        
        target_key = "amber-dev-key-2024"
        computed_hash = hash_api_key(target_key)
        print(f"DEBUG: Computed hash for '{target_key}' = {computed_hash}")
        
        # Get factory
        session_maker = _get_async_session_maker()

        async with session_maker() as session:
            # 2. Get the Development Key from DB
            query = select(ApiKey).where(ApiKey.name == "Development Key")
            result = await session.execute(query)
            key_records = result.scalars().all()
            
            if not key_records:
                print("ERROR: Key 'Development Key' NOT FOUND in DB.")
                return

            print(f"INFO: Found {len(key_records)} key(s) named 'Development Key'.")
            
            for key_record in key_records:
                print(f"DEBUG: Key ID={key_record.id}")
                print(f"DEBUG: Stored Hash = {key_record.hashed_key}")
                
                if computed_hash == key_record.hashed_key:
                    print("   -> MATCH! This key is valid.")
                else:
                    print("   -> MISMATCH.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
