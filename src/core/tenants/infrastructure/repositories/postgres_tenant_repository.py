from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.tenants.domain.ports.tenant_repository import TenantRepository
from src.core.tenants.domain.tenant import Tenant


class PostgresTenantRepository(TenantRepository):
    """
    PostgreSQL implementation of TenantRepository using SQLAlchemy.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, tenant_id: str) -> Tenant | None:
        """Retrieve a tenant by ID."""
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalars().first()
