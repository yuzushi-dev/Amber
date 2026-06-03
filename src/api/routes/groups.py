import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant_id, get_db_session, verify_tenant_admin
from src.core.admin_ops.domain.api_key import ApiKeyTenant
from src.core.ingestion.domain.folder import Folder
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.tenants.domain.group import (
    Group,
    GroupFolderAccess,
    GroupMember,
)

logger = logging.getLogger(__name__)

router = APIRouter()
me_router = APIRouter()


# --- Pydantic Models ---
class GroupCreate(BaseModel):
    name: str
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class GroupResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GroupMemberAdd(BaseModel):
    api_key_id: str
    role: str = "member"


class GroupMemberResponse(BaseModel):
    group_id: str
    api_key_id: str
    tenant_id: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GroupFolderGrant(BaseModel):
    folder_id: str
    access_mode: str = "read"


class GroupFolderResponse(BaseModel):
    id: str
    group_id: str
    folder_id: str
    tenant_id: str
    access_mode: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Helpers ---
async def _get_group_or_404(session: AsyncSession, group_id: str, tenant_id: str) -> Group:
    result = await session.execute(
        select(Group).where(Group.id == group_id, Group.tenant_id == tenant_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


# --- Group CRUD ---
@router.post(
    "", response_model=GroupResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_tenant_admin)],
)
async def create_group(
    group_in: GroupCreate,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Create a new group within the current tenant."""
    group = Group(
        id=str(uuid4()),
        tenant_id=tenant_id,
        name=group_in.name,
        description=group_in.description,
    )
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


@router.get("", response_model=list[GroupResponse])
async def list_groups(
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """List groups for the current tenant."""
    result = await session.execute(
        select(Group).where(Group.tenant_id == tenant_id).order_by(Group.name)
    )
    return result.scalars().all()


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Get a group by ID."""
    return await _get_group_or_404(session, group_id, tenant_id)


@router.patch("/{group_id}", response_model=GroupResponse, dependencies=[Depends(verify_tenant_admin)])
async def update_group(
    group_id: str,
    group_in: GroupUpdate,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Update a group's name, description, or active flag."""
    group = await _get_group_or_404(session, group_id, tenant_id)

    updates = group_in.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(group, field_name, value)

    await session.commit()
    await session.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_tenant_admin)])
async def delete_group(
    group_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Delete a group. Members and access grants cascade via FK constraints."""
    group = await _get_group_or_404(session, group_id, tenant_id)
    await session.delete(group)
    await session.commit()

    PostgresDocumentRepository.invalidate_visible_document_ids_cache()


# --- Members ---
@router.post(
    "/{group_id}/members", response_model=GroupMemberResponse,
    status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_tenant_admin)],
)
async def add_group_member(
    group_id: str,
    member_in: GroupMemberAdd,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Add an API key to the group. The API key must belong to the current tenant."""
    await _get_group_or_404(session, group_id, tenant_id)

    link_result = await session.execute(
        select(ApiKeyTenant.api_key_id).where(
            ApiKeyTenant.api_key_id == member_in.api_key_id,
            ApiKeyTenant.tenant_id == tenant_id,
        )
    )
    if link_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found in this tenant",
        )

    existing = await session.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.api_key_id == member_in.api_key_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="API key already a member"
        )

    member = GroupMember(
        group_id=group_id,
        api_key_id=member_in.api_key_id,
        tenant_id=tenant_id,
        role=member_in.role,
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)

    PostgresDocumentRepository.invalidate_visible_document_ids_cache()
    return member


@router.delete(
    "/{group_id}/members/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_tenant_admin)],
)
async def remove_group_member(
    group_id: str,
    api_key_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Remove an API key from the group."""
    await _get_group_or_404(session, group_id, tenant_id)

    result = await session.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.api_key_id == api_key_id,
            GroupMember.tenant_id == tenant_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    await session.delete(member)
    await session.commit()

    PostgresDocumentRepository.invalidate_visible_document_ids_cache()


@router.get("/{group_id}/members", response_model=list[GroupMemberResponse])
async def list_group_members(
    group_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """List members of a group."""
    await _get_group_or_404(session, group_id, tenant_id)

    result = await session.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.tenant_id == tenant_id,
        )
    )
    return result.scalars().all()


# --- Folder grants ---
@router.post(
    "/{group_id}/folders", response_model=GroupFolderResponse,
    status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_tenant_admin)],
)
async def grant_group_folder(
    group_id: str,
    grant_in: GroupFolderGrant,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Grant a group read access to all documents in a folder."""
    await _get_group_or_404(session, group_id, tenant_id)

    folder_result = await session.execute(
        select(Folder.id).where(
            Folder.id == grant_in.folder_id, Folder.tenant_id == tenant_id
        )
    )
    if folder_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found in this tenant"
        )

    existing = await session.execute(
        select(GroupFolderAccess).where(
            GroupFolderAccess.group_id == group_id,
            GroupFolderAccess.folder_id == grant_in.folder_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Folder already granted"
        )

    grant = GroupFolderAccess(
        id=str(uuid4()),
        group_id=group_id,
        folder_id=grant_in.folder_id,
        tenant_id=tenant_id,
        access_mode=grant_in.access_mode,
    )
    session.add(grant)
    await session.commit()
    await session.refresh(grant)

    PostgresDocumentRepository.invalidate_visible_document_ids_cache()
    return grant


@router.delete(
    "/{group_id}/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_tenant_admin)],
)
async def revoke_group_folder(
    group_id: str,
    folder_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Revoke a group's folder access grant."""
    await _get_group_or_404(session, group_id, tenant_id)

    result = await session.execute(
        select(GroupFolderAccess).where(
            GroupFolderAccess.group_id == group_id,
            GroupFolderAccess.folder_id == folder_id,
            GroupFolderAccess.tenant_id == tenant_id,
        )
    )
    grant = result.scalar_one_or_none()
    if not grant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found")

    await session.delete(grant)
    await session.commit()

    PostgresDocumentRepository.invalidate_visible_document_ids_cache()


@router.get("/{group_id}/folders", response_model=list[GroupFolderResponse])
async def list_group_folders(
    group_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """List folder grants for a group."""
    await _get_group_or_404(session, group_id, tenant_id)

    result = await session.execute(
        select(GroupFolderAccess).where(
            GroupFolderAccess.group_id == group_id,
            GroupFolderAccess.tenant_id == tenant_id,
        )
    )
    return result.scalars().all()


# --- Current user groups ---
@me_router.get("/groups", response_model=list[GroupResponse])
async def list_my_groups(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """List groups the current API key belongs to in the current tenant."""
    group_ids = getattr(request.state, "group_ids", [])
    if not group_ids:
        return []

    result = await session.execute(
        select(Group).where(
            Group.id.in_(group_ids),
            Group.tenant_id == tenant_id,
        ).order_by(Group.name)
    )
    return result.scalars().all()
