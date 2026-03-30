import asyncio
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from src.api.config import settings
from src.core.admin_ops.application.api_key_service import ApiKeyService
from src.core.database.session import configure_database, get_session_maker


async def create_key():
    # Initialize database
    configure_database(settings.db.database_url)
    session_maker = get_session_maker()

    async with session_maker() as session:
        service = ApiKeyService(session)
        # Create a super admin key so we can test everything
        result = await service.create_key(
            name="verification-key",
            scopes=["admin", "super_admin", "active_user"]
        )
        print(f"API_KEY={result['key']}")

        # Link to default tenant
        from sqlalchemy import select

        from src.core.admin_ops.domain.api_key import ApiKey as ApiKeyModel
        from src.core.admin_ops.domain.api_key import ApiKeyTenant

        # Find the key we just created
        stmt = select(ApiKeyModel).where(ApiKeyModel.id == result["id"])
        res = await session.execute(stmt)
        key_obj = res.scalar_one()

        # Check if already linked or link it
        api_key_tenant = ApiKeyTenant(
            api_key_id=key_obj.id,
            tenant_id="default",
            role="admin"
        )
        session.add(api_key_tenant)
        await session.commit()
        print("Key linked to 'default' tenant with 'admin' role.")

if __name__ == "__main__":
    asyncio.run(create_key())
