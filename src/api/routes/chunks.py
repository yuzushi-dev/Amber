"""
Chunk Retrieval Endpoint
========================

API routes for retrieving document chunks.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.context import get_current_tenant
from src.core.database.session import get_db
from src.core.models.chunk import Chunk
from src.core.models.document import Document
from src.shared.identifiers import DocumentId

router = APIRouter(tags=["documents"])


@router.get("/documents/{document_id}/chunks", response_model=List[dict])
async def get_document_chunks(
    document_id: str,
    tenant_id: str = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Retrieve all chunks for a specific document.
    """
    # 1. Verify document exists and belongs to tenant
    stmt = select(Document).where(
        Document.id == document_id, 
        Document.tenant_id == tenant_id
    )
    result = await session.execute(stmt)
    document = result.scalars().first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # 2. Fetch chunks
    # Order by index asc
    stmt = select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.index)
    result = await session.execute(stmt)
    chunks = result.scalars().all()
    
    # 3. Return simplified response (or use a Pydantic schema)
    # For now returning dicts to avoid circular imports or extra schema definition file creation in this step
    return [
        {
            "id": c.id,
            "index": c.index,
            "content": c.content,
            "tokens": c.tokens,
            "metadata": c.metadata_,
            "embedding_status": c.embedding_status
        }
        for c in chunks
    ]
