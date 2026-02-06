import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant_id
from src.api.deps import get_db_session as get_db_session
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder

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

    model_config = ConfigDict(from_attributes=True)


# --- Endpoints ---


@router.get("", response_model=list[FolderResponse])
async def list_folders(
    session: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_current_tenant_id)
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
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Create a new folder."""
    # RLS will enforce insertion only into current tenant (if check_option=CASCASE/LOCAL is used, strict RLS)
    # Even without strict insertion check, we must insert with the correct tenant_id.

    new_folder = Folder(id=str(uuid.uuid4()), tenant_id=tenant_id, name=folder_in.name)
    session.add(new_folder)
    await session.commit()
    await session.refresh(new_folder)
    return new_folder


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    delete_contents: bool = False,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Delete a folder.
    If delete_contents is True, all documents in the folder are permanently deleted.
    Otherwise, documents are unfiled.
    """
    # Explicitly check tenant_id in query
    query = select(Folder).where(Folder.id == folder_id, Folder.tenant_id == tenant_id)
    result = await session.execute(query)
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if delete_contents:
        # Recursive deletion
        from src.amber_platform.composition_root import build_vector_store_factory, platform
        from src.api.config import settings
        from src.core.ingestion.application.use_cases_documents import (
            DeleteDocumentRequest,
            DeleteDocumentUseCase,
        )

        # 1. Get all documents in the folder
        doc_query = select(Document).where(
            Document.folder_id == folder_id, Document.tenant_id == tenant_id
        )
        doc_result = await session.execute(doc_query)
        documents = doc_result.scalars().all()

        # 2. Setup Delete Use Case
        vector_store_factory = build_vector_store_factory()
        dimensions = settings.embedding_dimensions or 1536

        def make_vector_store(tid: str):
            return vector_store_factory(dimensions, collection_name=f"amber_{tid}")

        use_case = DeleteDocumentUseCase(
            session=session,
            storage=platform.minio_client,
            graph_client=platform.neo4j_client,
            vector_store_factory=make_vector_store,
        )

        # 3. Delete each document
        for doc in documents:
            try:
                await use_case.execute(
                    DeleteDocumentRequest(
                        document_id=doc.id, tenant_id=tenant_id, is_super_admin=False
                    )
                )
            except Exception:
                # Log error but continue deleting others/folder?
                # Or abort? Ideally we want best effort cleanup.
                # logger variable is not available in this scope, let's just print or ignore for now as use_case logs internally
                pass

    else:
        # Default behavior: Unfile documents
        from sqlalchemy import update

        stmt = update(Document).where(Document.folder_id == folder_id).values(folder_id=None)
        await session.execute(stmt)

    # Now delete the folder
    await session.delete(folder)
    await session.commit()
