"""
Background Tasks
================

Celery tasks for background document processing.
"""

import logging
import asyncio
from typing import Any

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from src.workers.celery_app import celery_app
from src.core.state.machine import DocumentStatus
from src.core.models.document import Document
from src.core.models.chunk import Chunk

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class BaseTask(Task):
    """Base task with common error handling."""
    
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300  # 5 minutes max
    retry_jitter = True
    max_retries = 3


@celery_app.task(bind=True, name="src.workers.tasks.health_check")
def health_check(self) -> dict:
    """
    Simple health check task for worker verification.

    Returns:
        dict: Health check result
    """
    return {
        "status": "healthy",
        "worker_id": self.request.id,
        "task": "health_check",
    }


@celery_app.task(
    bind=True, 
    name="src.workers.tasks.process_document",
    base=BaseTask,
    max_retries=3,
    default_retry_delay=60
)
def process_document(self, document_id: str, tenant_id: str) -> dict:
    """
    Process a document through the full ingestion pipeline.
    
    Steps:
    1. Fetch document from DB
    2. Update status to EXTRACTING
    3. Run extraction (FallbackManager)
    4. Update status to CLASSIFYING
    5. Run domain classification
    6. Update status to CHUNKING
    7. Run semantic chunking
    8. Update status to READY
    
    Args:
        document_id: ID of the document to process.
        tenant_id: Tenant for context.
        
    Returns:
        dict: Processing result summary.
    """
    logger.info(f"[Task {self.request.id}] Starting processing for document {document_id}")
    
    try:
        result = run_async(_process_document_async(document_id, tenant_id, self.request.id))
        logger.info(f"[Task {self.request.id}] Completed processing for document {document_id}")
        return result
        
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed processing document {document_id}: {e}")
        
        # Update document status to FAILED
        try:
            run_async(_mark_document_failed(document_id, str(e)))
        except Exception as fail_err:
            logger.error(f"Failed to mark document as failed: {fail_err}")
        
        # Retry if not exceeded
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error(f"[Task {self.request.id}] Max retries exceeded for document {document_id}")
            raise


@celery_app.task(
    bind=True,
    name="src.workers.tasks.process_communities",
    base=BaseTask,
    max_retries=2
)
def process_communities(self, tenant_id: str) -> dict:
    """
    Periodic or triggered task to update graph communities and summaries.
    """
    logger.info(f"[Task {self.request.id}] Updating communities for tenant {tenant_id}")
    try:
        result = run_async(_process_communities_async(tenant_id))
        return result
    except Exception as e:
        logger.error(f"Community processing failed: {e}")
        raise self.retry(exc=e)


async def _process_communities_async(tenant_id: str) -> dict:
    """Async implementation of community processing."""
    from src.core.graph.neo4j_client import neo4j_client
    from src.core.graph.communities.leiden import CommunityDetector
    from src.core.graph.communities.summarizer import CommunitySummarizer
    from src.core.graph.communities.embeddings import CommunityEmbeddingService
    from src.core.providers.factory import ProviderFactory
    from src.core.services.embeddings import EmbeddingService
    from src.api.config import settings

    # 1. Detection
    detector = CommunityDetector(neo4j_client)
    detect_res = await detector.detect_communities(tenant_id)
    
    if detect_res["status"] == "skipped":
        return detect_res

    # 2. Summarization
    factory = ProviderFactory(
        openai_api_key=settings.providers.openai_api_key,
        anthropic_api_key=settings.providers.anthropic_api_key
    )
    summarizer = CommunitySummarizer(neo4j_client, factory)
    
    # We summarize all that are now stale or new
    await summarizer.summarize_all_stale(tenant_id)
    
    # 3. Embeddings
    embedding_svc = EmbeddingService(
        openai_api_key=settings.providers.openai_api_key,
        model=settings.embeddings.default_model
    )
    comm_embedding_svc = CommunityEmbeddingService(embedding_svc)
    
    # Fetch all communities that need embedding (just summarized)
    # Actually, we can just fetch all 'ready' communities for this tenant for now
    # or track which ones were just updated.
    # For MVP, we'll re-sync all 'ready' communities to Milvus.
    query = """
    MATCH (c:Community {tenant_id: $tenant_id, status: 'ready'})
    RETURN c.id as id, c.tenant_id as tenant_id, c.level as level, c.title as title, c.summary as summary
    """
    ready_comms = await neo4j_client.execute_read(query, {"tenant_id": tenant_id})
    
    for comm in ready_comms:
        await comm_embedding_svc.embed_and_store_community(comm)

    return {
        "status": "success",
        "communities_detected": detect_res.get("community_count", 0),
        "communities_embedded": len(ready_comms)
    }


async def _process_document_async(document_id: str, tenant_id: str, task_id: str) -> dict:
    """
    Async implementation of document processing.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    
    from src.api.config import settings
    from src.core.models.document import Document
    from src.core.storage.minio_client import MinIOClient
    from src.core.services.ingestion import IngestionService
    from src.core.events.dispatcher import EventDispatcher, StateChangeEvent
    
    # Create async session
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Fetch document
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalars().first()
        
        if not document:
            raise ValueError(f"Document {document_id} not found")
            
        # Initialize services
        storage = MinIOClient()
        service = IngestionService(session, storage)
        
        # Publish starting event
        _publish_status(document_id, DocumentStatus.EXTRACTING.value, 10)
        
        # Process document (this does extraction, classification, chunking)
        await service.process_document(document_id)
        
        # Refresh to get final state
        await session.refresh(document)
        
        # Publish completion
        _publish_status(document_id, document.status.value, 100)
        
        # Get chunk count for stats
        from src.core.models.chunk import Chunk
        chunk_result = await session.execute(
            select(Chunk).where(Chunk.document_id == document_id)
        )
        chunks = chunk_result.scalars().all()
        
        return {
            "document_id": document_id,
            "status": document.status.value,
            "domain": document.domain,
            "chunk_count": len(chunks),
            "task_id": task_id
        }


async def _mark_document_failed(document_id: str, error: str):
    """Mark document as failed in DB."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    
    from src.api.config import settings
    from src.core.models.document import Document
    
    engine = create_async_engine(settings.db.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalars().first()
        
        if document:
            document.status = DocumentStatus.FAILED
            await session.commit()
            _publish_status(document_id, DocumentStatus.FAILED.value, 100, error=error)


def _publish_status(document_id: str, status: str, progress: int, error: str = None):
    """Publish status update to Redis Pub/Sub."""
    import json
    try:
        import redis
        from src.api.config import settings
        
        r = redis.Redis.from_url(settings.db.redis_url)
        channel = f"document:{document_id}:status"
        message = {
            "document_id": document_id,
            "status": status,
            "progress": progress
        }
        if error:
            message["error"] = error
            
        r.publish(channel, json.dumps(message))
        r.close()
    except Exception as e:
        logger.warning(f"Failed to publish status: {e}")
