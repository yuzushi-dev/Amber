"""
Admin API Keys
==============

Endpoints for managing API access keys.
"""

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_tenant_admin, get_current_tenant_id
from src.core.services.api_key_service import ApiKeyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/keys", tags=["admin-keys"])


# =============================================================================
# Schemas
# =============================================================================

class CreateKeyRequest(BaseModel):
    """Request to create a new API key."""
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default=["active_user"])
    prefix: str = Field("amber", min_length=2, max_length=10)
    
    # New fields for Tenant Scoping
    tenant_id: Optional[str] = None # Only Super Admin can set this arbitrarily
    role: str = "user" # 'user' or 'admin'


class ApiKeyTenantInfo(BaseModel):
    id: str
    name: str

class ApiKeyResponse(BaseModel):
    """API Key details (masked)."""
    id: str
    name: str
    prefix: str
    is_active: bool
    scopes: List[str] = []
    tenants: List[ApiKeyTenantInfo] = []
    last_chars: str
    created_at: datetime
    last_used_at: Optional[datetime] = None

    @field_validator('scopes', mode='before')
    @classmethod
    def scopes_none_to_list(cls, v):
        """Convert None to empty list for scopes field."""
        return v if v is not None else []


class CreatedKeyResponse(ApiKeyResponse):
    """Response including the raw secret key (only shown once)."""
    key: str


class UpdateKeyRequest(BaseModel):
    """Request to update an existing API key."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    scopes: Optional[List[str]] = None


class MeResponse(BaseModel):
    """Current API key information including scopes."""
    name: str
    scopes: List[str] = []
    tenant_id: Optional[str] = None


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/me", response_model=MeResponse)
async def get_my_key_info(
    request: Request
):
    """
    Get info about the current API key being used.
    """
    return MeResponse(
        name=getattr(request.state, "api_key_name", "Unknown"),
        scopes=getattr(request.state, "permissions", []),
        tenant_id=str(getattr(request.state, "tenant_id", ""))
    )


@router.get("", response_model=List[ApiKeyResponse], dependencies=[Depends(verify_tenant_admin)])
async def list_api_keys(
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    List active API keys.
    Super Admin: All keys (or filtered).
    Tenant Admin: Only keys linked to their tenant.
    """
    service = ApiKeyService(session)
    
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    if is_super:
        # Super Admin sees all keys
        # TODO: Add optional tenant_id query param for super admin filtering
        keys = await service.list_keys()
    else:
        # Tenant Admin sees only their tenant's keys
        keys = await service.list_keys(tenant_id=current_tenant)
    
    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            prefix=k.prefix,
            is_active=k.is_active,
            scopes=k.scopes,
            tenants=[ApiKeyTenantInfo(id=t.id, name=t.name) for t in k.tenants],
            last_chars=k.last_chars,
            created_at=k.created_at,
            last_used_at=k.last_used_at
        ) for k in keys
    ]


@router.post("", response_model=CreatedKeyResponse, dependencies=[Depends(verify_tenant_admin)])
async def create_api_key(
    request: Request,
    data: CreateKeyRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Generate a new API key.
    - Tenant Admin: Key is automatically linked to their tenant.
    - Super Admin: Can specify tenant_id, otherwise acts globally (careful!).
    """
    service = ApiKeyService(session)
    from src.core.services.tenant_service import TenantService
    tenant_service = TenantService(session)
    
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    # Determine target tenant
    target_tenant_id = None
    
    if is_super:
        target_tenant_id = data.tenant_id if data.tenant_id else None
    else:
        # Tenant Admin forces their own tenant
        target_tenant_id = current_tenant
    
    # Create the Key
    # NOTE: We might want to pass scopes. Admin can create 'admin' or 'user' key.
    # Should validation happen on scopes? 
    # For now, we allow them to set scopes passed in request (e.g. ['active_user', 'admin'])
    # In strict mode, we might limit Tenant Admin scopes.
    
    result = await service.create_key(
        name=data.name,
        prefix=data.prefix,
        scopes=data.scopes
    )
    
    # Link to Tenant if applicable
    if target_tenant_id:
        # Validate tenant existence
        tenant = await tenant_service.get_tenant(target_tenant_id)
        if not tenant:
             raise HTTPException(status_code=404, detail="Target tenant not found")
             
        await tenant_service.add_key_to_tenant(
            api_key_id=result["id"],
            tenant_id=target_tenant_id,
            role=data.role 
        )
        
        # Refresh the key object to get updated relation if needed, 
        # but `result` is a dict from create_key. 
        # We need to reconstruct the response structure or fetch the key again 
        # to show the tenant in the response.
        # However, for efficiency, we can just append to the dict if we knew the structure matches.
        # Let's fetch the full key to be safe and consistent.
        # Actually create_key returns a dict, list_keys returns objects. 
        # Let's assume the frontend re-fetches or we construct the response object manually.
        pass
    
    return CreatedKeyResponse(
        id=result["id"],
        name=result["name"],
        prefix=result["prefix"],
        is_active=True,
        scopes=result["scopes"],
        last_chars=result["key"][-4:],
        created_at=result["created_at"],
        key=result["key"],
        # Tenants might be empty in the immediate result unless we fetch
        tenants=[ApiKeyTenantInfo(id=tenant.id, name=tenant.name)] if target_tenant_id and tenant else []
    )


@router.patch("/{key_id}", response_model=ApiKeyResponse, dependencies=[Depends(verify_tenant_admin)])
async def update_api_key(
    key_id: str,
    data: UpdateKeyRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Update an existing API key.
    Tenant Admin can only update keys belonging to their tenant.
    """
    service = ApiKeyService(session)
    from src.core.services.tenant_service import TenantService
    tenant_service = TenantService(session)
    
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    # Check ownership
    # We need to fetch the key and its tenants
    # ApiKeyService doesn't have get_key_with_tenants exposed easily? validate_key does hash lookup.
    # We need get_key_by_id in service ideally, or use db directly here or search in list?
    # list_keys returns all, we can filter. But inefficient.
    # Let's verify via tenant_service.get_tenant_keys maybe? 
    # Or just fetch key and check relations.
    
    # Using SQL directly for permission check to keep it optimized
    from sqlalchemy import select
    from src.core.models.api_key import ApiKey, ApiKeyTenant
    from sqlalchemy.orm import selectinload
    
    query = select(ApiKey).where(ApiKey.id == key_id).options(selectinload(ApiKey.tenants))
    result = await session.execute(query)
    key = result.scalars().first()
    
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
        
    if not is_super:
        # Check if key is linked to current_tenant
        is_linked = any(t.id == current_tenant for t in key.tenants)
        if not is_linked:
             raise HTTPException(status_code=403, detail="Cannot manage this key")

    # Proceed update
    updated_key = await service.update_key(
        key_id=key_id,
        name=data.name,
        scopes=data.scopes
    )
    
    return ApiKeyResponse(
        id=updated_key.id,
        name=updated_key.name,
        prefix=updated_key.prefix,
        is_active=updated_key.is_active,
        scopes=updated_key.scopes,
        tenants=[ApiKeyTenantInfo(id=t.id, name=t.name) for t in updated_key.tenants],
        last_chars=updated_key.last_chars,
        created_at=updated_key.created_at,
        last_used_at=updated_key.last_used_at
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_tenant_admin)])
async def revoke_api_key(
    key_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Revoke (deactivate) an API key.
    """
    service = ApiKeyService(session)
    
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    # Ownership verification (duplicate logic, could be a dependency/helper)
    from sqlalchemy import select
    from src.core.models.api_key import ApiKey
    from sqlalchemy.orm import selectinload
    
    query = select(ApiKey).where(ApiKey.id == key_id).options(selectinload(ApiKey.tenants))
    result = await session.execute(query)
    key = result.scalars().first()
    
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
        
    if not is_super:
        is_linked = any(t.id == current_tenant for t in key.tenants)
        if not is_linked:
             raise HTTPException(status_code=403, detail="Cannot manage this key")

    await service.revoke_key(key_id)


class KeyTenantLink(BaseModel):
    tenant_id: str
    role: str = "user"


@router.post("/{key_id}/tenants", dependencies=[Depends(verify_tenant_admin)])
async def link_key_to_tenant(
    key_id: str,
    link: KeyTenantLink,
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Link an API key to a tenant.
    Tenant Admin can only link keys to THEIR OWN tenant (and they must probably own the key too).
    """
    from src.core.services.tenant_service import TenantService
    tenant_service = TenantService(session)
    
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    if not is_super:
        # Tenant Admin can only link to THEIR tenant
        if link.tenant_id != current_tenant:
             raise HTTPException(status_code=403, detail="Cannot link to other tenants")
        
        # Verify they effectively 'own' the key? 
        # Actually, if they created the key, it's already linked. 
        # If they want to add a *second* link to *another* tenant they own (unlikely in this model), allowed.
        # But if the key is effectively orphaned (no tenants), can they claim it? 
        # Security risk: Claiming a global key? 
        # Safe bet: They can only operate on keys ALREADY linked to them (to change role) 
        # OR keys that are newly created (handled in create).
        # Adding a NEW link to a key usually implies sharing a key across tenants.
        # Simplification: Only Super Admin can multi-tenant a key. 
        # ERROR: Tenant Admin trying to link an EXISTING key to their tenant...
        # If the key is NOT linked to them, they can't even see it (in list).
        # So they can't get the ID easily unless guessing.
        # Let's restrict Link/Unlink to Super Admin or strict ownership.
        
        # For simplicity and security: Explicit usage of this endpoint is SUPER ADMIN only.
        # Tenant Admin links key via CREATE endpoint automatically.
        raise HTTPException(status_code=403, detail="Manual linking restricted to Super Admin")

    success = await tenant_service.add_key_to_tenant(key_id, link.tenant_id, link.role)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to link key"
        )
    return {"message": "Linked"}


@router.delete("/{key_id}/tenants/{tenant_id}", dependencies=[Depends(verify_tenant_admin)])
async def unlink_key_from_tenant(
    key_id: str,
    tenant_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Unlink an API key from a tenant.
    """
    from src.core.services.tenant_service import TenantService
    tenant_service = TenantService(session)
    
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    if not is_super:
        if tenant_id != current_tenant:
             raise HTTPException(status_code=403, detail="Cannot unlink from other tenants")
        # Removing the link to self = removing access. Allowed.
        
    success = await tenant_service.remove_key_from_tenant(key_id, tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found"
        )
    return {"message": "Unlinked"}
