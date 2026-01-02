"""
Chunk Retrieval Endpoint
========================

API routes for retrieving document chunks.
"""

from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.context import get_current_tenant
from src.core.database.session import get_db
from src.core.models.chunk import Chunk
from src.core.models.document import Document
from src.shared.identifiers import DocumentId

router = APIRouter(tags=["documents"])


@router.get("/documents/{document_id}/chunks", response_model=Dict[str, Any])
async def get_document_chunks(
    document_id: str,
    limit: int = 50,
    offset: int = 0,
    tenant_id: str = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Retrieve chunks for a specific document with pagination.

    Args:
        document_id: Document UUID
        limit: Maximum number of chunks to return (default: 50)
        offset: Number of chunks to skip (default: 0)
        tenant_id: Tenant ID from context
        session: Database session

    Returns:
        Dict with chunks, total count, limit, and offset
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

    # 2. Get total count
    count_stmt = select(func.count(Chunk.id)).where(Chunk.document_id == document_id)
    total = await session.scalar(count_stmt)

    # 3. Fetch chunks with pagination
    stmt = (
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.index)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    chunks = result.scalars().all()

    # 4. Return paginated response
    return {
        "chunks": [
            {
                "id": c.id,
                "index": c.index,
                "content": c.content,
                "tokens": c.tokens,
                "metadata": c.metadata_,
                "embedding_status": c.embedding_status
            }
            for c in chunks
        ],
        "total": total or 0,
        "limit": limit,
        "offset": offset
    }
