from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from src.api.deps import get_db_session as get_db_session, get_current_tenant_id
from src.core.ingestion.domain.folder import Folder
from src.core.ingestion.domain.document import Document

router = APIRouter()

# --- Pydantic Models ---
class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class FolderUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class FolderResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True

# --- Endpoints ---

@router.get("", response_model=List[FolderResponse])
async def list_folders(
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id)
):
    """List all folders for the tenant."""
    # RLS filters automatically, but we add explicit filter for safety/clarity
    query = select(Folder).where(Folder.tenant_id == tenant_id).order_by(Folder.name)
    result = await session.execute(query)
    return result.scalars().all()

@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    folder_in: FolderCreate,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id)
):
    """Create a new folder."""
    # RLS will enforce insertion only into current tenant (if check_option=CASCASE/LOCAL is used, strict RLS)
    # Even without strict insertion check, we must insert with the correct tenant_id.
    
    new_folder = Folder(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=folder_in.name
    )
    session.add(new_folder)
    await session.commit()
    await session.refresh(new_folder)
    return new_folder

@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id)
):
    """
    Delete a folder. 
    Documents in this folder are unfiled.
    """
    # Explicity check tenant_id in query for consistency (RLS also handles it)
    query = select(Folder).where(Folder.id == folder_id, Folder.tenant_id == tenant_id)
    result = await session.execute(query)
    folder = result.scalar_one_or_none()
    
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Unfile documents
    # Using explicit query to update documents belonging to this folder AND this tenant (though folder_id is unique globally usually)
    # RLS on documents ensures we only update our own documents.
    from sqlalchemy import update
    stmt = update(Document).where(Document.folder_id == folder_id).values(folder_id=None)
    await session.execute(stmt)
    
    # Now delete the folder
    await session.delete(folder)
    await session.commit()
