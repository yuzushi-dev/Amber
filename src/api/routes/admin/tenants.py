from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_tenant_admin, verify_super_admin, get_current_tenant_id
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

@router.get("", response_model=List[TenantResponse], dependencies=[Depends(verify_tenant_admin)])
async def list_tenants(
    request: Request,
    skip: int = 0, 
    limit: int = 100, 
    session: AsyncSession = Depends(get_db_session)
):
    """
    List tenants.
    Super Admin: All tenants.
    Tenant Admin: Only current tenant.
    """
    service = TenantService(session)
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    if is_super:
        tenants = await service.list_tenants(skip, limit)
    else:
        # Tenant Admin sees only their own tenant
        # We can reuse get_tenant but need to return a list
        t = await service.get_tenant(current_tenant)
        tenants = [t] if t else []
    
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

@router.post("", response_model=TenantResponse, dependencies=[Depends(verify_super_admin)])
async def create_tenant(
    data: TenantCreate, 
    session: AsyncSession = Depends(get_db_session)
):
    """
    Create a new tenant.
    Restricted to Super Admin.
    """
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

@router.get("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(verify_tenant_admin)])
async def get_tenant(
    tenant_id: str, 
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get tenant details.
    """
    service = TenantService(session)
    
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    if not is_super:
        if tenant_id != current_tenant:
             raise HTTPException(status_code=403, detail="Cannot access this tenant")

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

@router.patch("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(verify_tenant_admin)])
async def update_tenant(
    tenant_id: str, 
    data: TenantUpdate, 
    request: Request,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Update tenant details.
    Tenant Admin can update their own tenant.
    """
    service = TenantService(session)
    
    # Permission Check
    is_super = getattr(request.state, "is_super_admin", False)
    current_tenant = get_current_tenant_id(request)
    
    if not is_super:
        if tenant_id != current_tenant:
             raise HTTPException(status_code=403, detail="Cannot update this tenant")
        
        # Prevent Tenant Admin from changing critical fields? 
        # e.g. disabling themselves or changing prefix?
        # For now, allow all updates in schema (name/config/prefix).
        # Assuming Tenant Admin is trusted with own config.
        pass

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

@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_super_admin)])
async def delete_tenant(
    tenant_id: str, 
    session: AsyncSession = Depends(get_db_session)
):
    """
    Delete a tenant.
    Restricted to Super Admin.
    """
    service = TenantService(session)
    success = await service.delete_tenant(tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Tenant not found"
        )
