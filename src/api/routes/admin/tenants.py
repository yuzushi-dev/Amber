from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_admin
from src.core.tenants.application.tenant_service import TenantService

router = APIRouter(prefix="/tenants", tags=["admin-tenants"])


class TenantCreate(BaseModel):
    name: str
    api_key_prefix: str | None = None
    config: dict | None = None


class TenantUpdate(BaseModel):
    name: str | None = None
    api_key_prefix: str | None = None
    config: dict | None = None
    is_active: bool | None = None


class TenantKeySummary(BaseModel):
    id: str
    name: str
    prefix: str
    last_chars: str
    is_active: bool
    scopes: list[str] = []

    @field_validator("scopes", mode="before")
    @classmethod
    def scopes_none_to_list(cls, v):
        """Convert None to empty list for scopes field."""
        return v if v is not None else []

    model_config = ConfigDict(from_attributes=True)


class TenantResponse(BaseModel):
    id: str
    name: str
    api_key_prefix: str | None
    is_active: bool
    config: dict = {}
    created_at: datetime | None = None
    api_keys: list[TenantKeySummary] = []
    document_count: int = 0

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[TenantResponse], dependencies=[Depends(verify_admin)])
async def list_tenants(
    skip: int = 0, limit: int = 100, session: AsyncSession = Depends(get_db_session)
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
async def create_tenant(data: TenantCreate, session: AsyncSession = Depends(get_db_session)):
    service = TenantService(session)
    if data.api_key_prefix:
        existing = await service.get_tenant_by_prefix(data.api_key_prefix)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="API key prefix already in use"
            )

    tenant = await service.create_tenant(data.name, data.api_key_prefix, data.config)
    # New tenants have 0 documents
    t_model = TenantResponse.model_validate(tenant)
    t_model.document_count = 0
    return t_model


@router.get("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(verify_admin)])
async def get_tenant(tenant_id: str, session: AsyncSession = Depends(get_db_session)):
    service = TenantService(session)
    tenant = await service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    counts = await service.get_tenant_document_counts([tenant.id])
    t_model = TenantResponse.model_validate(tenant)
    t_model.document_count = counts.get(tenant.id, 0)
    return t_model


@router.patch("/{tenant_id}", response_model=TenantResponse, dependencies=[Depends(verify_admin)])
async def update_tenant(
    tenant_id: str, data: TenantUpdate, session: AsyncSession = Depends(get_db_session)
):
    service = TenantService(session)
    tenant = await service.update_tenant(tenant_id, **data.model_dump(exclude_unset=True))
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    counts = await service.get_tenant_document_counts([tenant.id])
    t_model = TenantResponse.model_validate(tenant)
    t_model.document_count = counts.get(tenant.id, 0)
    return t_model


async def cleanup_tenant_resources(tenant_id: str):
    """Cleanup external resources for a tenant."""
    from logging import getLogger

    logger = getLogger(__name__)

    # 1. Cleanup Neo4j
    try:
        from src.amber_platform.composition_root import platform

        await platform.neo4j_client.delete_tenant_data(tenant_id)
    except Exception as e:
        logger.error(f"Failed to cleanup Neo4j for tenant {tenant_id}: {e}")

    # 2. Cleanup Milvus
    try:
        from src.amber_platform.composition_root import build_vector_store_factory
        from src.api.config import settings

        vector_store_factory = build_vector_store_factory()
        # Dimensions don't match for deletion but required for config, using default
        vector_store = vector_store_factory(settings.embedding_dimensions or 1536)
        await vector_store.delete_tenant_collection(tenant_id)
    except Exception as e:
        logger.error(f"Failed to cleanup Milvus for tenant {tenant_id}: {e}")


@router.delete(
    "/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_admin)]
)
async def delete_tenant(tenant_id: str, session: AsyncSession = Depends(get_db_session)):
    service = TenantService(session)
    success = await service.delete_tenant(tenant_id, cleanup_callback=cleanup_tenant_resources)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
