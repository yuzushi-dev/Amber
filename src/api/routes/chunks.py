"""
Chunk Retrieval Endpoint
========================

API routes for retrieving document chunks.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.session import get_db
from src.core.models.chunk import Chunk, EmbeddingStatus
from src.core.models.document import Document
from src.shared.context import get_current_tenant
from src.api.schemas.chunks import ChunkUpdate
from src.api.config import settings
from src.core.services.embeddings import EmbeddingService
from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore
from src.core.graph.neo4j_client import neo4j_client

import tiktoken
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


@router.get("/documents/{document_id}/chunks", response_model=dict[str, Any])
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


@router.put("/documents/{document_id}/chunks/{chunk_id}")
async def update_chunk(
    document_id: str,
    chunk_id: str,
    update_data: ChunkUpdate,
    tenant_id: str = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Update a chunk's content and regenerate its embedding.
    """
    # 1. Verify chunk exists
    stmt = select(Chunk).where(
        Chunk.id == chunk_id,
        Chunk.document_id == document_id
    )
    result = await session.execute(stmt)
    chunk = result.scalars().first()

    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk not found"
        )

    # 2. Update content and tokens
    chunk.content = update_data.content
    
    # Calculate tokens
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        chunk.tokens = len(encoding.encode(update_data.content))
    except Exception:
        # Fallback estimation
        chunk.tokens = len(update_data.content) // 4

    chunk.embedding_status = EmbeddingStatus.PENDING
    await session.commit()
    await session.refresh(chunk)

    # 3. Regenerate Embedding (Sync for responsiveness)
    try:
        # Initialize services
        embedding_service = EmbeddingService(
            openai_api_key=settings.openai_api_key or None,
        )
        
        milvus_config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=f"amber_{tenant_id}",
        )
        vector_store = MilvusVectorStore(milvus_config)

        # Generate embedding
        embeddings, _ = await embedding_service.embed_texts([chunk.content])
        embedding = embeddings[0]

        # Upsert to Milvus
        chunk_data = {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "tenant_id": tenant_id,
            "content": chunk.content[:65530],
            "embedding": embedding,
            **chunk.metadata_
        }
        await vector_store.upsert_chunks([chunk_data])
        await vector_store.disconnect()

        # Update status
        chunk.embedding_status = EmbeddingStatus.COMPLETED
        await session.commit()

    except Exception as e:
        logger.error(f"Failed to update chunk embedding: {e}")
        chunk.embedding_status = EmbeddingStatus.FAILED
        await session.commit()
        # Return success but indicate partial failure? 
        # Or just let the UI see "failed".

    return {
        "id": chunk.id,
        "content": chunk.content,
        "tokens": chunk.tokens,
        "embedding_status": chunk.embedding_status
    }


@router.delete("/documents/{document_id}/chunks/{chunk_id}")
async def delete_chunk(
    document_id: str,
    chunk_id: str,
    tenant_id: str = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Delete a chunk from Postgres, Milvus, and Neo4j.
    """
    # 1. Get Chunk
    stmt = select(Chunk).where(
        Chunk.id == chunk_id,
        Chunk.document_id == document_id
    )
    result = await session.execute(stmt)
    chunk = result.scalars().first()

    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk not found"
        )

    # 2. Delete from Milvus
    try:
        milvus_config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=f"amber_{tenant_id}",
        )
        vector_store = MilvusVectorStore(milvus_config)
        await vector_store.delete_chunks([chunk_id], tenant_id)
        await vector_store.disconnect()
    except Exception as e:
        logger.error(f"Failed to delete from Milvus: {e}")
        # Continue to delete from DB

    # 3. Delete from Neo4j
    try:
        await neo4j_client.execute_write(
            "MATCH (c:Chunk {id: $chunk_id}) DETACH DELETE c",
            {"chunk_id": chunk_id}
        )
    except Exception as e:
        logger.error(f"Failed to delete from Neo4j: {e}")

    # 4. Delete from Postgres
    await session.delete(chunk)
    await session.commit()

    return {"status": "success", "message": "Chunk deleted"}
