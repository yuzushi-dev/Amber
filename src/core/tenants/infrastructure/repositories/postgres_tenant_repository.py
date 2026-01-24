from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.tenants.domain.tenant import Tenant
from src.core.tenants.domain.ports.tenant_repository import TenantRepository

class PostgresTenantRepository(TenantRepository):
    """
    PostgreSQL implementation of TenantRepository using SQLAlchemy.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, tenant_id: str) -> Optional[Tenant]:
        """Retrieve a tenant by ID."""
        result = await self._session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        return result.scalars().first()
