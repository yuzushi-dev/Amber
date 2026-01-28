"""
Backup Background Tasks
=======================

Celery tasks for background backup and restore processing.
"""

import logging
from datetime import datetime, UTC

from src.workers.celery_app import celery_app
from src.workers.tasks import BaseTask, run_async

logger = logging.getLogger(__name__)


def _publish_backup_status(job_id: str, status: str, progress: int, error: str = None):
    """Publish backup status update to Redis Pub/Sub."""
    import json
    try:
        import redis
        from src.api.config import settings
        
        r = redis.Redis.from_url(settings.db.redis_url)
        try:
            channel = f"backup:{job_id}:status"
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
        logger.warning(f"Failed to publish backup status: {e}")


def _publish_restore_status(job_id: str, status: str, progress: int, error: str = None):
    """Publish restore status update to Redis Pub/Sub."""
    import json
    try:
        import redis
        from src.api.config import settings
        
        r = redis.Redis.from_url(settings.db.redis_url)
        try:
            channel = f"restore:{job_id}:status"
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
        logger.warning(f"Failed to publish restore status: {e}")


@celery_app.task(
    bind=True,
    name="src.workers.backup_tasks.create_backup",
    base=BaseTask,
    max_retries=2
)
def create_backup(self, job_id: str, tenant_id: str, scope: str) -> dict:
    """
    Create a system backup.
    
    This task:
    1. Updates BackupJob status to RUNNING
    2. Generates ZIP file with backup data based on scope
    3. Uploads to MinIO
    4. Updates BackupJob with result path and status
    
    Args:
        job_id: The BackupJob ID
        tenant_id: Tenant to backup
        scope: "user_data" or "full_system"
        
    Returns:
        dict: Backup result summary
    """
    logger.info(f"[Task {self.request.id}] Starting backup job {job_id} for tenant {tenant_id}, scope={scope}")
    
    try:
        result = run_async(_create_backup_async(job_id, tenant_id, scope, self.request.id))
        logger.info(f"[Task {self.request.id}] Completed backup job {job_id}")
        return result
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed backup job {job_id}: {e}")
        
        # Mark job as failed
        try:
            run_async(_mark_backup_failed(job_id, str(e)))
        except Exception as fail_err:
            logger.error(f"Failed to mark backup as failed: {fail_err}")
        
        raise


async def _create_backup_async(job_id: str, tenant_id: str, scope: str, task_id: str) -> dict:
    """Async implementation of backup task."""
    from src.workers.tasks import deep_reset_singletons
    deep_reset_singletons()

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    
    from src.api.config import settings
    from src.core.admin_ops.domain.backup_job import BackupJob, BackupStatus, BackupScope
    from src.core.admin_ops.application.backup_service import BackupService
    from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
    
    engine = create_async_engine(settings.db.database_url)
    
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            # Fetch and update job status to RUNNING
            result = await session.execute(
                select(BackupJob).where(BackupJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if not job:
                raise ValueError(f"BackupJob {job_id} not found")
            
            job.status = BackupStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await session.commit()
            
            _publish_backup_status(job_id, "running", 5)
            
            # Generate backup
            storage = MinIOClient()
            backup_service = BackupService(session, storage)
            
            def progress_callback(progress: int):
                # Scale progress: 5% start, 95% for generation
                scaled = 5 + int(progress * 0.9)
                job.progress = scaled
                _publish_backup_status(job_id, "running", scaled)
            
            # Convert scope string to enum
            backup_scope = BackupScope(scope)
            
            storage_path, file_size = await backup_service.create_backup(
                tenant_id=tenant_id,
                job_id=job_id,
                scope=backup_scope,
                progress_callback=progress_callback
            )
            
            # Update job with results
            job.status = BackupStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.result_path = storage_path
            job.file_size = file_size
            job.progress = 100
            await session.commit()
            
            _publish_backup_status(job_id, "completed", 100)
            
            return {
                "job_id": job_id,
                "status": "completed",
                "storage_path": storage_path,
                "file_size": file_size,
                "task_id": task_id
            }
    finally:
        await engine.dispose()


async def _mark_backup_failed(job_id: str, error: str):
    """Mark backup job as failed in DB."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    
    from src.api.config import settings
    from src.core.admin_ops.domain.backup_job import BackupJob, BackupStatus
    
    engine = create_async_engine(settings.db.database_url)
    
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            result = await session.execute(
                select(BackupJob).where(BackupJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if job:
                job.status = BackupStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error_message = error
                await session.commit()
                
                _publish_backup_status(job_id, "failed", 100, error=error)
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="src.workers.backup_tasks.restore_backup",
    base=BaseTask,
    max_retries=1
)
def restore_backup(self, job_id: str, tenant_id: str, backup_path: str, mode: str) -> dict:
    """
    Restore from a backup file.
    
    Args:
        job_id: The RestoreJob ID
        tenant_id: Target tenant
        backup_path: Path to backup file in storage
        mode: "merge" or "replace"
        
    Returns:
        dict: Restore result summary
    """
    logger.info(f"[Task {self.request.id}] Starting restore job {job_id} for tenant {tenant_id}, mode={mode}")
    
    try:
        result = run_async(_restore_backup_async(job_id, tenant_id, backup_path, mode, self.request.id))
        logger.info(f"[Task {self.request.id}] Completed restore job {job_id}")
        return result
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed restore job {job_id}: {e}")
        
        try:
            run_async(_mark_restore_failed(job_id, str(e)))
        except Exception as fail_err:
            logger.error(f"Failed to mark restore as failed: {fail_err}")
        
        raise


async def _restore_backup_async(job_id: str, tenant_id: str, backup_path: str, mode: str, task_id: str) -> dict:
    """Async implementation of restore task."""
    from src.workers.tasks import deep_reset_singletons
    deep_reset_singletons()
    
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    
    from src.api.config import settings
    from src.core.admin_ops.domain.backup_job import RestoreJob, BackupStatus, RestoreMode
    from src.core.admin_ops.application.restore_service import RestoreService
    from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
    
    engine = create_async_engine(settings.db.database_url)
    
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            # Fetch and update job status to RUNNING
            result = await session.execute(
                select(RestoreJob).where(RestoreJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if not job:
                raise ValueError(f"RestoreJob {job_id} not found")
            
            job.status = BackupStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await session.commit()
            
            _publish_restore_status(job_id, "running", 5)
            
            # Perform restore
            storage = MinIOClient()
            restore_service = RestoreService(session, storage)
            
            def progress_callback(progress: int):
                scaled = 5 + int(progress * 0.9)
                job.progress = scaled
                _publish_restore_status(job_id, "running", scaled)
            
            restore_mode = RestoreMode(mode)
            
            restore_result = await restore_service.restore(
                backup_path=backup_path,
                target_tenant_id=tenant_id,
                mode=restore_mode,
                progress_callback=progress_callback
            )
            
            # Update job with results
            if restore_result.errors:
                job.status = BackupStatus.FAILED
                job.error_message = "; ".join(restore_result.errors)
                status_str = "failed"
            else:
                job.status = BackupStatus.COMPLETED
                status_str = "completed"

            job.completed_at = datetime.now(UTC)
            job.items_restored = restore_result.total_items
            job.progress = 100
            
            await session.commit()
            
            _publish_restore_status(job_id, status_str, 100)
            
            return {
                "job_id": job_id,
                "status": status_str,
                "items_restored": restore_result.total_items,
                "folders": restore_result.folders_restored,
                "documents": restore_result.documents_restored,
                "conversations": restore_result.conversations_restored,
                "facts": restore_result.facts_restored,
                "errors": restore_result.errors,
                "task_id": task_id
            }
    finally:
        await engine.dispose()


async def _mark_restore_failed(job_id: str, error: str):
    """Mark restore job as failed in DB."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    
    from src.api.config import settings
    from src.core.admin_ops.domain.backup_job import RestoreJob, BackupStatus
    
    engine = create_async_engine(settings.db.database_url)
    
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            result = await session.execute(
                select(RestoreJob).where(RestoreJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if job:
                job.status = BackupStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error_message = error
                await session.commit()
                
                _publish_restore_status(job_id, "failed", 100, error=error)
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="src.workers.backup_tasks.scheduled_backup",
    base=BaseTask
)
def scheduled_backup(self, tenant_id: str, scope: str) -> dict:
    """
    Task triggered by Celery Beat for scheduled backups.
    Creates a new BackupJob and then delegates to create_backup.
    """
    from uuid import uuid4
    
    logger.info(f"[Scheduled] Starting backup for tenant {tenant_id}, scope={scope}")
    
    job_id = str(uuid4())
    
    try:
        result = run_async(_create_scheduled_backup_job(job_id, tenant_id, scope))
        
        # Trigger the main backup task
        create_backup.delay(job_id, tenant_id, scope)
        
        return {"job_id": job_id, "status": "scheduled"}
    except Exception as e:
        logger.error(f"Failed to create scheduled backup: {e}")
        raise


async def _create_scheduled_backup_job(job_id: str, tenant_id: str, scope: str):
    """Create a BackupJob record for scheduled backup."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    
    from src.api.config import settings
    from src.core.admin_ops.domain.backup_job import BackupJob, BackupScope, BackupStatus
    
    engine = create_async_engine(settings.db.database_url)
    
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            job = BackupJob(
                id=job_id,
                tenant_id=tenant_id,
                scope=BackupScope(scope),
                status=BackupStatus.PENDING,
                is_scheduled="true"
            )
            session.add(job)
            await session.commit()
    finally:
        await engine.dispose()
