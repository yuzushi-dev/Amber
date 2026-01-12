"""
Admin API Keys
==============

Endpoints for managing API access keys.
"""

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
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


class ApiKeyResponse(BaseModel):
    """API Key details (masked)."""
    id: str
    name: str
    prefix: str
    is_active: bool
    scopes: List[str]
    last_chars: str
    created_at: datetime
    last_used_at: Optional[datetime] = None


class CreatedKeyResponse(ApiKeyResponse):
    """Response including the raw secret key (only shown once)."""
    key: str


# =============================================================================
# Endpoints
# =============================================================================

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
