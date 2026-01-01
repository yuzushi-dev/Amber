"""
Backfill Embeddings Script
===========================

This script backfills embeddings for existing chunks that don't have embeddings in Milvus.
"""

import asyncio
import logging
import sys

# Ensure packages are loadable
if "/app/.packages" not in sys.path:
    sys.path.insert(0, "/app/.packages")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill_embeddings():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    
    from src.api.config import settings
    from src.core.models.chunk import Chunk, EmbeddingStatus
    from src.core.models.document import Document
    from src.core.services.embeddings import EmbeddingService
    from src.core.vector_store.milvus import MilvusVectorStore, MilvusConfig
    
    logger.info("Starting embedding backfill...")
    
    # Connect to DB
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get all chunks with PENDING status
        query = select(Chunk).where(Chunk.embedding_status == EmbeddingStatus.PENDING)
        result = await session.execute(query)
        pending_chunks = result.scalars().all()
        
        if not pending_chunks:
            logger.info("No pending chunks found.")
            return {"status": "skipped", "reason": "no_pending_chunks"}
        
        logger.info(f"Found {len(pending_chunks)} pending chunks")
        
        # Group by document to get tenant_id
        doc_ids = list(set(c.document_id for c in pending_chunks))
        
        doc_query = select(Document).where(Document.id.in_(doc_ids))
        doc_result = await session.execute(doc_query)
        docs = {d.id: d for d in doc_result.scalars().all()}
        
        # Initialize embedding service
        embedding_service = EmbeddingService(
            openai_api_key=settings.openai_api_key or None,
        )
        
        # Process in batches
        batch_size = 50
        total_embedded = 0
        
        for i in range(0, len(pending_chunks), batch_size):
            batch = pending_chunks[i:i+batch_size]
            logger.info(f"Processing batch {i//batch_size + 1} ({len(batch)} chunks)")
            
            # Group by tenant for Milvus
            tenant_chunks = {}
            for chunk in batch:
                doc = docs.get(chunk.document_id)
                if not doc:
                    continue
                tenant_id = doc.tenant_id
                if tenant_id not in tenant_chunks:
                    tenant_chunks[tenant_id] = []
                tenant_chunks[tenant_id].append((chunk, doc))
            
            for tenant_id, chunk_doc_pairs in tenant_chunks.items():
                chunks = [c for c, _ in chunk_doc_pairs]
                contents = [c.content for c in chunks]
                
                # Generate embeddings
                embeddings, stats = await embedding_service.embed_texts(contents)
                
                # Prepare for Milvus
                milvus_config = MilvusConfig(
                    host=settings.db.milvus_host,
                    port=settings.db.milvus_port,
                    collection_name=f"amber_{tenant_id}",
                )
                vector_store = MilvusVectorStore(milvus_config)
                
                milvus_data = [
                    {
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "tenant_id": tenant_id,
                        "content": chunk.content[:65530],
                        "embedding": emb,
                    }
                    for chunk, emb in zip(chunks, embeddings)
                ]
                
                await vector_store.upsert_chunks(milvus_data)
                await vector_store.disconnect()
                
                # Update chunk status
                for chunk in chunks:
                    chunk.embedding_status = EmbeddingStatus.COMPLETED
                
                total_embedded += len(chunks)
                logger.info(f"Embedded {len(chunks)} chunks for tenant {tenant_id}")
        
        await session.commit()
        logger.info(f"Backfill complete. Total embedded: {total_embedded}")
        
        return {"status": "success", "embedded_count": total_embedded}


if __name__ == "__main__":
    result = asyncio.run(backfill_embeddings())
    print(result)
