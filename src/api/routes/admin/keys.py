"""
Admin API Keys
==============

Endpoints for managing API access keys.
"""

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_admin
from src.core.services.api_key_service import ApiKeyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/keys", tags=["admin-keys"])


# =============================================================================
# Schemas
# =============================================================================

class CreateKeyRequest(BaseModel):
    """Request to create a new API key."""
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default=["admin", "active_user"])
    prefix: str = Field("amber", min_length=2, max_length=10)


class ApiKeyTenantInfo(BaseModel):
    id: str
    name: str

class ApiKeyResponse(BaseModel):
    """API Key details (masked)."""
    id: str
    name: str
    prefix: str
    is_active: bool
    scopes: List[str]
    tenants: List[ApiKeyTenantInfo] = []
    last_chars: str
    created_at: datetime
    last_used_at: Optional[datetime] = None


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
    scopes: List[str]
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


@router.get("", response_model=List[ApiKeyResponse], dependencies=[Depends(verify_admin)])
async def list_api_keys(
    session: AsyncSession = Depends(get_db_session)
):
    """
    List all active API keys.
    """
    service = ApiKeyService(session)
    keys = await service.list_keys()
    
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


@router.post("", response_model=CreatedKeyResponse, dependencies=[Depends(verify_admin)])
async def create_api_key(
    request: CreateKeyRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Generate a new API key.
    The secret key is returned only in this response and cannot be retrieved later.
    """
    service = ApiKeyService(session)
    result = await service.create_key(
        name=request.name,
        prefix=request.prefix,
        scopes=request.scopes
    )
    
    return CreatedKeyResponse(
        id=result["id"],
        name=result["name"],
        prefix=result["prefix"],
        is_active=True,
        scopes=result["scopes"],
        last_chars=result["key"][-4:],
        created_at=result["created_at"],
        key=result["key"]
    )


@router.patch("/{key_id}", response_model=ApiKeyResponse, dependencies=[Depends(verify_admin)])
async def update_api_key(
    key_id: str,
    request: UpdateKeyRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Update an existing API key's name or scopes.
    """
    service = ApiKeyService(session)
    key = await service.update_key(
        key_id=key_id,
        name=request.name,
        scopes=request.scopes
    )
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
        
    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        is_active=key.is_active,
        scopes=key.scopes,
        tenants=[ApiKeyTenantInfo(id=t.id, name=t.name) for t in key.tenants],
        last_chars=key.last_chars,
        created_at=key.created_at,
        last_used_at=key.last_used_at
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_admin)])
async def revoke_api_key(
    key_id: str,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Revoke (deactivate) an API key.
    """
    service = ApiKeyService(session)
    success = await service.revoke_key(key_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )


class KeyTenantLink(BaseModel):
    tenant_id: str
    role: str = "user"


@router.post("/{key_id}/tenants", dependencies=[Depends(verify_admin)])
async def link_key_to_tenant(
    key_id: str,
    link: KeyTenantLink,
    session: AsyncSession = Depends(get_db_session)
):
    """Link an API key to a tenant."""
    from src.core.services.tenant_service import TenantService
    tenant_service = TenantService(session)
    success = await tenant_service.add_key_to_tenant(key_id, link.tenant_id, link.role)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to link key to tenant (check IDs)"
        )
    return {"message": "Linked"}


@router.delete("/{key_id}/tenants/{tenant_id}", dependencies=[Depends(verify_admin)])
async def unlink_key_from_tenant(
    key_id: str,
    tenant_id: str,
    session: AsyncSession = Depends(get_db_session)
):
    """Unlink an API key from a tenant."""
    from src.core.services.tenant_service import TenantService
    tenant_service = TenantService(session)
    success = await tenant_service.remove_key_from_tenant(key_id, tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found"
        )
    return {"message": "Unlinked"}
