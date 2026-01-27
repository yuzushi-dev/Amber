"""
Tenant Service
==============

Service for managing tenants and their associations with API keys.
"""

from typing import Optional, Callable, Awaitable
from uuid import uuid4

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.tenants.domain.tenant import Tenant
from src.core.tenants.application.active_vector_collection import ensure_active_vector_collection_config
from src.core.admin_ops.domain.api_key import ApiKey, ApiKeyTenant
from src.core.ingestion.domain.document import Document


class TenantService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_tenant(
        self,
        name: str,
        api_key_prefix: Optional[str] = None,
        config: Optional[dict] = None
    ) -> Tenant:
        """Create a new tenant."""
        tenant = Tenant(
            name=name,
            api_key_prefix=api_key_prefix,
            config=config or {}
        )
        self.session.add(tenant)
        await self.session.flush()
        tenant.config = ensure_active_vector_collection_config(tenant.id, tenant.config)
        await self.session.commit()
        await self.session.refresh(tenant)
        return tenant

    async def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get a tenant by ID."""
        query = select(Tenant).where(Tenant.id == tenant_id).options(selectinload(Tenant.api_keys))
        result = await self.session.execute(query)
        return result.scalars().first()
    
    async def get_tenant_by_prefix(self, prefix: str) -> Optional[Tenant]:
        """Get a tenant by API key prefix."""
        query = select(Tenant).where(Tenant.api_key_prefix == prefix).options(selectinload(Tenant.api_keys))
        result = await self.session.execute(query)
        return result.scalars().first()

    async def list_tenants(self, skip: int = 0, limit: int = 100) -> list[Tenant]:
        """List all tenants."""
        query = select(Tenant).offset(skip).limit(limit).options(selectinload(Tenant.api_keys))
        result = await self.session.execute(query)
        return result.scalars().all()

    async def update_tenant(self, tenant_id: str, **kwargs) -> Optional[Tenant]:
        """Update a tenant."""
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            return None
            
        for key, value in kwargs.items():
            if hasattr(tenant, key):
                setattr(tenant, key, value)
                
        await self.session.commit()
        await self.session.refresh(tenant)
        return tenant

    async def delete_tenant(self, tenant_id: str, cleanup_callback: Optional[Callable[[str], Awaitable[None]]] = None) -> bool:
        """
        Delete a tenant and all associated data.
        Performs cleanup in:
        1. External services (via callback)
        2. Postgres (Tenant record cascade)
        """
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            return False
            
        # 1. External Cleanup
        if cleanup_callback:
            try:
                await cleanup_callback(tenant_id)
            except Exception as e:
                # Log but continue to ensure we don't block deletion on partial failure
                from logging import getLogger
                getLogger(__name__).error(f"Failed to cleanup external resources for tenant {tenant_id}: {e}")

        # 2. Cleanup Postgres
        await self.session.delete(tenant)
        await self.session.commit()
        return True

    async def add_key_to_tenant(self, api_key_id: str, tenant_id: str, role: str = "user") -> bool:
        """Link an API key to a tenant with a specific role."""
        # Check if already exists
        link = await self.session.get(ApiKeyTenant, (api_key_id, tenant_id))
        if link:
            link.role = role
        else:
            link = ApiKeyTenant(api_key_id=api_key_id, tenant_id=tenant_id, role=role)
            self.session.add(link)
            
        try:
            await self.session.commit()
            return True
        except Exception:
            await self.session.rollback()
            return False

    async def remove_key_from_tenant(self, api_key_id: str, tenant_id: str) -> bool:
        """Unlink an API key from a tenant."""
        link = await self.session.get(ApiKeyTenant, (api_key_id, tenant_id))
        if link:
            await self.session.delete(link)
            await self.session.commit()
            return True
        return False
        
    async def get_tenant_keys(self, tenant_id: str) -> list[ApiKey]:
        """Get all API keys linked to a tenant."""
        query = select(ApiKey).join(ApiKeyTenant).where(
            ApiKeyTenant.tenant_id == tenant_id
        ).options(selectinload(ApiKey.tenants))
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_tenant_document_counts(self, tenant_ids: list[str]) -> dict[str, int]:
        """Get document counts for a list of tenants."""
        if not tenant_ids:
            return {}
            
        query = select(
            Document.tenant_id, 
            func.count(Document.id)
        ).where(
            Document.tenant_id.in_(tenant_ids)
        ).group_by(Document.tenant_id)
        
        result = await self.session.execute(query)
        return {row[0]: row[1] for row in result.all()}
