"""
Export Background Tasks
=======================

Celery tasks for background conversation export processing.
"""

import logging
from datetime import datetime, UTC

from src.workers.celery_app import celery_app
from src.workers.tasks import BaseTask, run_async

logger = logging.getLogger(__name__)


def _publish_export_status(job_id: str, status: str, progress: int, error: str = None):
    """Publish export status update to Redis Pub/Sub."""
    import json
    try:
        import redis
        from src.api.config import settings
        
        r = redis.Redis.from_url(settings.db.redis_url)
        try:
            channel = f"export:{job_id}:status"
            message = {
                "job_id": job_id,
                "status": status,
                "progress": progress
            }
            if error:
                message["error"] = error
            
            r.publish(channel, json.dumps(message))
        finally:
            r.close()
    except Exception as e:
        logger.warning(f"Failed to publish export status: {e}")


@celery_app.task(
    bind=True,
    name="src.workers.export_tasks.export_all_conversations",
    base=BaseTask,
    max_retries=2
)
def export_all_conversations(self, job_id: str, tenant_id: str) -> dict:
    """
    Export all conversations for a tenant.
    
    This task:
    1. Updates ExportJob status to RUNNING
    2. Generates ZIP file with all conversations
    3. Uploads to MinIO
    4. Updates ExportJob with result path and status
    
    Args:
        job_id: The ExportJob ID
        tenant_id: Tenant to export conversations for
        
    Returns:
        dict: Export result summary
    """
    logger.info(f"[Task {self.request.id}] Starting export job {job_id} for tenant {tenant_id}")
    
    try:
        result = run_async(_export_all_conversations_async(job_id, tenant_id, self.request.id))
        logger.info(f"[Task {self.request.id}] Completed export job {job_id}")
        return result
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed export job {job_id}: {e}")
        
        # Mark job as failed
        try:
            run_async(_mark_export_failed(job_id, str(e)))
        except Exception as fail_err:
            logger.error(f"Failed to mark export as failed: {fail_err}")
        
        raise


async def _export_all_conversations_async(job_id: str, tenant_id: str, task_id: str) -> dict:
    """Async implementation of export task."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    
    from src.api.config import settings
    from src.core.models.export_job import ExportJob, ExportStatus
    from src.core.services.export_service import ExportService
    from src.core.storage.storage_client import MinIOClient
    
    engine = create_async_engine(settings.db.database_url)
    
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            # Fetch and update job status to RUNNING
            result = await session.execute(
                select(ExportJob).where(ExportJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if not job:
                raise ValueError(f"ExportJob {job_id} not found")
            
            job.status = ExportStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await session.commit()
            
            _publish_export_status(job_id, "running", 5)
            
            # Generate export
            storage = MinIOClient()
            export_service = ExportService(session, storage)
            
            def progress_callback(progress: int):
                # Scale progress: 5% start, 95% for generation
                scaled = 5 + int(progress * 0.9)
                _publish_export_status(job_id, "running", scaled)
            
            storage_path, file_size = await export_service.generate_all_conversations_zip(
                tenant_id=tenant_id,
                job_id=job_id,
                progress_callback=progress_callback
            )
            
            # Update job with results
            job.status = ExportStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.result_path = storage_path
            job.file_size = str(file_size)
            await session.commit()
            
            _publish_export_status(job_id, "completed", 100)
            
            return {
                "job_id": job_id,
                "status": "completed",
                "storage_path": storage_path,
                "file_size": file_size,
                "task_id": task_id
            }
    finally:
        await engine.dispose()


async def _mark_export_failed(job_id: str, error: str):
    """Mark export job as failed in DB."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    
    from src.api.config import settings
    from src.core.models.export_job import ExportJob, ExportStatus
    
    engine = create_async_engine(settings.db.database_url)
    
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            result = await session.execute(
                select(ExportJob).where(ExportJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if job:
                job.status = ExportStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error_message = error
                await session.commit()
                
                _publish_export_status(job_id, "failed", 100, error=error)
    finally:
        await engine.dispose()
