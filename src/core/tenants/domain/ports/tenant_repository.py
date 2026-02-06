from typing import Protocol

from src.core.tenants.domain.tenant import Tenant


class TenantRepository(Protocol):
    """
    Port for Tenant persistence operations.
    """

    async def get(self, tenant_id: str) -> Tenant | None:
        """Retrieve a tenant by ID."""
        ...
