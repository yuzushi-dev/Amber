from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_admin
from src.core.services.tenant_service import TenantService
from src.core.models.tenant import Tenant

router = APIRouter(prefix="/tenants", tags=["admin-tenants"])

class TenantCreate(BaseModel):
    name: str
    api_key_prefix: Optional[str] = None
    config: Optional[dict] = None

class TenantUpdate(BaseModel):
    name: Optional[str] = None
    api_key_prefix: Optional[str] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None

from datetime import datetime

class TenantKeySummary(BaseModel):
    id: str
    name: str
    prefix: str
    last_chars: str
    is_active: bool
    scopes: List[str] = []

    @field_validator('scopes', mode='before')
    @classmethod
    def scopes_none_to_list(cls, v):
        """Convert None to empty list for scopes field."""
        return v if v is not None else []

    class Config:
        from_attributes = True

class TenantResponse(BaseModel):
    id: str
    name: str
    api_key_prefix: Optional[str]
    is_active: bool
    config: dict = {}
    created_at: Optional[datetime] = None
    api_keys: List[TenantKeySummary] = []
    document_count: int = 0

    class Config:
        from_attributes = True

@router.get("", response_model=List[TenantResponse], dependencies=[Depends(verify_admin)])
async def list_tenants(
    skip: int = 0, 
    limit: int = 100, 
    session: AsyncSession = Depends(get_db_session)
):
    service = TenantService(session)
    tenants = await service.list_tenants(skip, limit)
    
    # Enrich with document counts
    if tenants:
        tenant_ids = [t.id for t in tenants]
        counts = await service.get_tenant_document_counts(tenant_ids)
        
        # Transform to Pydantic models manually to inject count
        results = []
        for t in tenants:
            t_model = TenantResponse.model_validate(t)
            t_model.document_count = counts.get(t.id, 0)
            results.append(t_model)
            
        return results
        
    return []

@router.post("", response_model=TenantResponse, dependencies=[Depends(verify_admin)])
async def create_tenant(
    data: TenantCreate, 
    session: AsyncSession = Depends(get_db_session)
):
    service = TenantService(session)
    if data.api_key_prefix:
        existing = await service.get_tenant_by_prefix(data.api_key_prefix)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key prefix already in use"
            )
            
    tenant = await service.create_tenant(data.name, data.api_key_prefix, data.config)
    # New tenants have 0 documents
    t_model = TenantResponse.model_validate(tenant)
    t_model.document_count = 0
    return t_model

@router.get("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(verify_admin)])
async def get_tenant(
    tenant_id: str, 
    session: AsyncSession = Depends(get_db_session)
):
    service = TenantService(session)
    tenant = await service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Tenant not found"
        )
    
    counts = await service.get_tenant_document_counts([tenant.id])
    t_model = TenantResponse.model_validate(tenant)
    t_model.document_count = counts.get(tenant.id, 0)
    return t_model

@router.patch("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(verify_admin)])
async def update_tenant(
    tenant_id: str, 
    data: TenantUpdate, 
    session: AsyncSession = Depends(get_db_session)
):
    service = TenantService(session)
    tenant = await service.update_tenant(tenant_id, **data.model_dump(exclude_unset=True))
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Tenant not found"
        )
    
    counts = await service.get_tenant_document_counts([tenant.id])
    t_model = TenantResponse.model_validate(tenant)
    t_model.document_count = counts.get(tenant.id, 0)
    return t_model

@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_admin)])
async def delete_tenant(
    tenant_id: str, 
    session: AsyncSession = Depends(get_db_session)
):
    service = TenantService(session)
    success = await service.delete_tenant(tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Tenant not found"
        )
