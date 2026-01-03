"""
Stale Document Recovery
=======================

Handles recovery of documents stuck in processing states after worker restart.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


async def recover_stale_documents() -> dict[str, Any]:
    """
    Find and recover documents stuck in processing states.
    
    This function is called on worker startup to handle documents that were
    left in intermediate states due to worker crashes or restarts.
    
    Recovery Logic:
    1. Query documents with status in ('extracting', 'classifying', 'chunking')
    2. For each document:
       - If has chunks and status is 'chunking' -> mark as 'ready'
       - Otherwise -> mark as 'failed' with error message
    3. Publish status updates via Redis for UI consistency
    
    Returns:
        dict: {"recovered": int, "failed": int, "total": int}
    """
    from src.api.config import settings
    from src.core.models.document import Document
    from src.core.models.chunk import Chunk
    from src.core.state.machine import DocumentStatus
    
    # Processing states that indicate incomplete work
    STALE_STATES = [
        DocumentStatus.EXTRACTING.value,
        DocumentStatus.CLASSIFYING.value,
        DocumentStatus.CHUNKING.value,
    ]
    
    logger.info("Starting stale document recovery check...")
    
    try:
        # Create async session
        engine = create_async_engine(settings.db.database_url)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        recovered = 0
        failed = 0
        total = 0
        
        async with async_session() as session:
            # Find all documents in stale states
            result = await session.execute(
                select(Document).where(Document.status.in_(STALE_STATES))
            )
            stale_documents = result.scalars().all()
            total = len(stale_documents)
            
            if total == 0:
                logger.info("No stale documents found")
                return {"recovered": 0, "failed": 0, "total": 0}
            
            logger.info(f"Found {total} stale document(s) to process")
            
            for document in stale_documents:
                try:
                    # Check if document has chunks
                    chunk_result = await session.execute(
                        select(Chunk).where(Chunk.document_id == document.id).limit(1)
                    )
                    has_chunks = chunk_result.scalars().first() is not None
                    
                    if document.status == DocumentStatus.CHUNKING.value and has_chunks:
                        # Document was in final stage with chunks - likely completed
                        document.status = DocumentStatus.READY
                        document.updated_at = datetime.now(timezone.utc)
                        recovered += 1
                        logger.info(
                            f"Recovered document {document.id} ({document.filename}) -> READY"
                        )
                    else:
                        # Document was interrupted before completion - mark as failed
                        document.status = DocumentStatus.FAILED
                        document.updated_at = datetime.now(timezone.utc)
                        # Store error info if model supports it
                        if hasattr(document, 'error_message'):
                            document.error_message = (
                                f"Processing interrupted by worker restart. "
                                f"Previous state: {document.status}. "
                                f"Please retry document upload."
                            )
                        failed += 1
                        logger.warning(
                            f"Marked document {document.id} ({document.filename}) as FAILED "
                            f"(was in {document.status} state)"
                        )
                    
                    # Publish status update via Redis
                    _publish_recovery_status(
                        document.id, 
                        document.status.value if hasattr(document.status, 'value') else document.status
                    )
                    
                except Exception as e:
                    logger.error(f"Error processing stale document {document.id}: {e}")
                    failed += 1
            
            # Commit all changes
            await session.commit()
        
        # Close engine
        await engine.dispose()
        
        logger.info(
            f"Stale document recovery complete: "
            f"{recovered} recovered, {failed} failed, {total} total"
        )
        
        return {"recovered": recovered, "failed": failed, "total": total}
        
    except Exception as e:
        logger.error(f"Stale document recovery failed: {e}")
        return {"recovered": 0, "failed": 0, "total": 0, "error": str(e)}


def _publish_recovery_status(document_id: str, status: str) -> None:
    """Publish recovery status update to Redis Pub/Sub."""
    import json
    try:
        import redis
        from src.api.config import settings
        
        r = redis.Redis.from_url(settings.db.redis_url)
        channel = f"document:{document_id}:status"
        message = {
            "document_id": document_id,
            "status": status,
            "progress": 100,
            "recovered": True,
            "message": f"Document status updated by recovery process to: {status}"
        }
        r.publish(channel, json.dumps(message))
        r.close()
    except Exception as e:
        logger.debug(f"Failed to publish recovery status: {e}")


def run_recovery_sync() -> dict[str, Any]:
    """
    Synchronous wrapper for recovery function.
    Used by Celery signals which run in sync context.
    """
    import asyncio
    
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(recover_stale_documents())
    finally:
        loop.close()
