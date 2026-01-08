from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from src.api.deps import get_db_session
from src.core.models.folder import Folder
from src.core.models.document import Document

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
    # Assuming single tenant for experimental context, or derived from user
    tenant_id: str = "default"
):
    """List all folders for the tenant."""
    query = select(Folder).where(Folder.tenant_id == tenant_id).order_by(Folder.name)
    result = await session.execute(query)
    return result.scalars().all()

@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    folder_in: FolderCreate,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = "default"
):
    """Create a new folder."""
    # Check for duplicate names? (Optional for now)
    
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
    session: AsyncSession = Depends(get_db_session)
):
    """
    Delete a folder. 
    Documents in this folder should be unfiled (folder_id set to NULL).
    """
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Unfile documents is handled by ORM if we didn't use cascade delete.
    # But wait, in the model I set `cascade="all, delete-orphan"` on `Folder.documents`.
    # Wait, that would DELETE the documents! That's dangerous. 
    # The user said "I cannot delete them also". Usually deleting a folder usually 
    # implies unfiling or recursive delete. 
    # Standard safe behavior: Unfile documents.
    # I should UPDATE the model relationship or manually nullify here.
    # Let's inspect the model I defined earlier.
    # `documents: Mapped[List["Document"]] = relationship("Document", back_populates="folder", cascade="all, delete-orphan")`
    # This WILL delete documents. I should fix the model first to NOT delete documents by default. 
    # Or I should strictly nullify them here before deleting the folder object to avoid cascade trigger.
    
    # Let's nullify explicitly to be safe.
    from sqlalchemy import update
    stmt = update(Document).where(Document.folder_id == folder_id).values(folder_id=None)
    await session.execute(stmt)
    
    # Now delete the folder
    await session.delete(folder)
    await session.commit()
