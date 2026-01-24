from typing import Protocol, Optional
from src.core.tenants.domain.tenant import Tenant

class TenantRepository(Protocol):
    """
    Port for Tenant persistence operations.
    """
    
    async def get(self, tenant_id: str) -> Optional[Tenant]:
        """Retrieve a tenant by ID."""
        ...
