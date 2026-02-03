import asyncio
import os
import sys

# Ensure project root is in path
sys.path.append(os.getcwd())

from src.core.database.session import async_session_maker, configure_database
from src.core.admin_ops.application.api_key_service import ApiKeyService
from src.core.tenants.domain.tenant import Tenant
from sqlalchemy import select

async def main():
    print("Seeding test database...")
    
    # Configure database
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    
    configure_database(database_url)
    
    dev_key = os.getenv("DEV_API_KEY", "amber-dev-key-2024")
    
    async with async_session_maker() as session:
        # 1. Ensure Default Tenant Exists
        result = await session.execute(select(Tenant).where(Tenant.id == 'default'))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            print("Creating default tenant...")
            tenant = Tenant(
                id='default',
                name='Test Tenant',
                api_key_prefix='amber_',
                is_active=True,
                config={
                    "embedding_model": "text-embedding-3-small",
                    "generation_model": "gpt-4.1-mini"
                }
            )
            session.add(tenant)
            await session.commit()
            print("Default tenant created.")
        else:
            print("Default tenant already exists.")

        # 2. Ensure API Key Exists
        print(f"Ensuring API key exists: {dev_key}")
        service = ApiKeyService(session)
        # ensure_bootstrap_key logic might require looking at its signature, 
        # but passing the key string is usually main arg.
        # Based on src/api/main.py: await service.ensure_bootstrap_key(dev_key, name="Development Key")
        await service.ensure_bootstrap_key(dev_key, name="Test Key")
        print(f"API Key populated.")

if __name__ == "__main__":
    asyncio.run(main())
