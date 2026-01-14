import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.core.models.api_key import ApiKey, ApiKeyTenant
from src.core.models.tenant import Tenant
from src.core.database.session import async_session_maker
from sqlalchemy import select

async def main():
    try:
        async with async_session_maker() as session:
            # Get default tenant
            result = await session.execute(select(Tenant).where(Tenant.id == 'default'))
            tenant = result.scalar_one_or_none()
            
            if not tenant:
                print("Tenant 'default' not found.")
                return

            # Find keys with 'super_admin' scope
            # Note: scopes is a JSON column, so we might need to fetch all and filter in python if DB filter is complex
            result = await session.execute(select(ApiKey))
            all_keys = result.scalars().all()
            
            super_admin_keys = [k for k in all_keys if k.scopes and 'super_admin' in k.scopes]
            
            print(f"Found {len(super_admin_keys)} Super Admin keys.")
            
            for key in super_admin_keys:
                print(f"Linking key '{key.name}' to tenant '{tenant.name}'...")
                
                # Check if already linked
                link_exists = await session.execute(
                    select(ApiKeyTenant).where(
                        ApiKeyTenant.api_key_id == key.id,
                        ApiKeyTenant.tenant_id == tenant.id
                    )
                )
                if link_exists.scalar_one_or_none():
                    print(f"Key '{key.name}' already linked.")
                    continue

                # Link key
                link = ApiKeyTenant(
                    api_key_id=key.id,
                    tenant_id=tenant.id,
                    role='admin' # Super key should be admin in the tenant
                )
                session.add(link)
                
            if super_admin_keys:
                await session.commit()
                print("Keys linked successfully.")
            else:
                print("No Super Admin keys found to link.")
                
            # Verify linkage
            await session.refresh(tenant)
            print(f"Tenant '{tenant.name}' now has {len(tenant.api_keys)} keys.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
