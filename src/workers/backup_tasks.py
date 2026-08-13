"""
Backup Background Tasks
=======================

Celery tasks for background backup and restore processing.
"""

import logging
from datetime import UTC, datetime

from src.workers.celery_app import celery_app
from src.workers.tasks import BaseTask, run_async

logger = logging.getLogger(__name__)


def _publish_backup_status(job_id: str, status: str, progress: int, error: str = None):
    """Publish backup status update to Redis Pub/Sub and cache last known state."""
    import json

    try:
        import redis

        from src.api.config import settings

        r = redis.Redis.from_url(settings.db.redis_url)
        try:
            channel = f"backup:{job_id}:status"
            message = {"job_id": job_id, "status": status, "progress": progress}
            if error:
                message["error"] = error

            payload = json.dumps(message)
            r.publish(channel, payload)
            # Cache state for polling clients (1h TTL)
            r.setex(f"backup:state:{job_id}", 3600, payload)
        finally:
            r.close()
    except Exception as e:
        logger.warning(f"Failed to publish backup status: {e}")


def _publish_restore_status(job_id: str, status: str, progress: int, error: str = None):
    """Publish restore status update to Redis Pub/Sub and cache last known state."""
    import json

    try:
        import redis

        from src.api.config import settings

        r = redis.Redis.from_url(settings.db.redis_url)
        try:
            channel = f"restore:{job_id}:status"
            message = {"job_id": job_id, "status": status, "progress": progress}
            if error:
                message["error"] = error

            payload = json.dumps(message)
            r.publish(channel, payload)
            r.setex(f"restore:state:{job_id}", 3600, payload)
        finally:
            r.close()
    except Exception as e:
        logger.warning(f"Failed to publish restore status: {e}")


@celery_app.task(
    bind=True, name="src.workers.backup_tasks.create_backup", base=BaseTask, max_retries=2
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
    logger.info(
        f"[Task {self.request.id}] Starting backup job {job_id} for tenant {tenant_id}, scope={scope}"
    )

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
    from src.core.admin_ops.application.backup_service import BackupService
    from src.core.admin_ops.domain.backup_job import BackupJob, BackupScope, BackupStatus
    from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session
            await configure_worker_session(session)
            # Fetch and update job status to RUNNING
            result = await session.execute(select(BackupJob).where(BackupJob.id == job_id))
            job = result.scalar_one_or_none()

            if not job:
                raise ValueError(f"BackupJob {job_id} not found")

            job.status = BackupStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await session.commit()

            _publish_backup_status(job_id, "running", 5)

            # Generate backup
            storage = MinIOClient()
            from src.amber_platform.composition_root import build_vector_store_factory, platform

            backup_service = BackupService(
                session, storage, platform.neo4j_client, build_vector_store_factory()
            )

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
                progress_callback=progress_callback,
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
                "task_id": task_id,
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

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session
            await configure_worker_session(session)
            result = await session.execute(select(BackupJob).where(BackupJob.id == job_id))
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
    bind=True, name="src.workers.backup_tasks.restore_backup", base=BaseTask, max_retries=1
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
    logger.info(
        f"[Task {self.request.id}] Starting restore job {job_id} for tenant {tenant_id}, mode={mode}"
    )

    try:
        result = run_async(
            _restore_backup_async(job_id, tenant_id, backup_path, mode, self.request.id)
        )
        logger.info(f"[Task {self.request.id}] Completed restore job {job_id}")
        return result
    except Exception as e:
        logger.error(f"[Task {self.request.id}] Failed restore job {job_id}: {e}")

        try:
            run_async(_mark_restore_failed(job_id, str(e)))
        except Exception as fail_err:
            logger.error(f"Failed to mark restore as failed: {fail_err}")

        raise


async def _restore_backup_async(
    job_id: str, tenant_id: str, backup_path: str, mode: str, task_id: str
) -> dict:
    """Async implementation of restore task."""
    from src.workers.tasks import deep_reset_singletons

    deep_reset_singletons()

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    from src.core.admin_ops.application.restore_service import RestoreService
    from src.core.admin_ops.domain.backup_job import BackupStatus, RestoreJob, RestoreMode
    from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session
            await configure_worker_session(session)
            # Fetch and update job status to RUNNING
            result = await session.execute(select(RestoreJob).where(RestoreJob.id == job_id))
            job = result.scalar_one_or_none()

            if not job:
                raise ValueError(f"RestoreJob {job_id} not found")

            job.status = BackupStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await session.commit()

            _publish_restore_status(job_id, "running", 5)

            # Perform restore
            storage = MinIOClient()
            from src.amber_platform.composition_root import build_vector_store_factory, platform

            restore_service = RestoreService(
                session, storage, platform.neo4j_client, build_vector_store_factory()
            )

            def progress_callback(progress: int):
                scaled = 5 + int(progress * 0.9)
                job.progress = scaled
                _publish_restore_status(job_id, "running", scaled)

            restore_mode = RestoreMode(mode)

            restore_result = await restore_service.restore(
                backup_path=backup_path,
                target_tenant_id=tenant_id,
                mode=restore_mode,
                progress_callback=progress_callback,
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
                "conversations_without_owner": restore_result.conversations_without_owner,
                "facts_without_owner": restore_result.facts_without_owner,
                "errors": restore_result.errors,
                "task_id": task_id,
            }
    finally:
        await engine.dispose()


async def _mark_restore_failed(job_id: str, error: str):
    """Mark restore job as failed in DB."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    from src.core.admin_ops.domain.backup_job import BackupStatus, RestoreJob

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session
            await configure_worker_session(session)
            result = await session.execute(select(RestoreJob).where(RestoreJob.id == job_id))
            job = result.scalar_one_or_none()

            if job:
                job.status = BackupStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error_message = error
                await session.commit()

                _publish_restore_status(job_id, "failed", 100, error=error)
    finally:
        await engine.dispose()


@celery_app.task(bind=True, name="src.workers.backup_tasks.scheduled_backup", base=BaseTask)
def scheduled_backup(self, tenant_id: str, scope: str) -> dict:
    """
    Task triggered by Celery Beat for scheduled backups.
    Creates a new BackupJob and then delegates to create_backup.
    """
    from uuid import uuid4

    logger.info(f"[Scheduled] Starting backup for tenant {tenant_id}, scope={scope}")

    job_id = str(uuid4())

    try:
        run_async(_create_scheduled_backup_job(job_id, tenant_id, scope))

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

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            from src.core.database.session import configure_worker_session
            await configure_worker_session(session)
            job = BackupJob(
                id=job_id,
                tenant_id=tenant_id,
                scope=BackupScope(scope),
                status=BackupStatus.PENDING,
                is_scheduled=True,
            )
            session.add(job)
            await session.commit()
    finally:
        await engine.dispose()


@celery_app.task(bind=True, name="src.workers.backup_tasks.check_due_backups", base=BaseTask)
def check_due_backups(self) -> dict:
    """
    Heartbeat task invoked by Celery Beat every minute.

    Scans BackupSchedule for enabled schedules and dispatches `scheduled_backup`
    when the configured time slot has arrived and the last run is from a previous
    slot. After dispatching, applies retention pruning by removing oldest backups
    above `retention_count` (DB row + MinIO file).
    """
    try:
        return run_async(_check_due_backups_async())
    except Exception as e:
        logger.error(f"check_due_backups failed: {e}")
        raise


async def _check_due_backups_async() -> dict:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    from src.core.admin_ops.domain.backup_job import BackupSchedule

    now = datetime.now(UTC)
    dispatched: list[str] = []
    pruned: list[str] = []

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            from src.core.database.session import configure_worker_session

            await configure_worker_session(session)

            result = await session.execute(
                select(BackupSchedule).where(BackupSchedule.enabled.is_(True))
            )
            schedules = result.scalars().all()

            for sched in schedules:
                if not _is_schedule_due(sched, now):
                    continue

                logger.info(
                    f"[Heartbeat] Dispatching scheduled backup for tenant={sched.tenant_id}, "
                    f"freq={sched.frequency}, time={sched.time_utc}"
                )

                # Mark the schedule as having run for this slot so the next tick
                # within the same minute does not dispatch again.
                sched.last_run_at = now
                sched.last_run_status = "dispatched"
                await session.flush()

                scope_value = sched.scope.value if sched.scope else "user_data"
                scheduled_backup.delay(sched.tenant_id, scope_value)
                dispatched.append(sched.tenant_id)

                # Retention: keep only the latest N completed scheduled backups per tenant.
                pruned_ids = await _prune_old_backups(
                    session, sched.tenant_id, sched.retention_count
                )
                pruned.extend(pruned_ids)

            await session.commit()
    finally:
        await engine.dispose()

    return {"dispatched": dispatched, "pruned": pruned, "now": now.isoformat()}


def _is_schedule_due(schedule, now: datetime) -> bool:
    """Decide if a schedule is due to run.

    Period-based instead of exact-minute matching: a schedule is due when the
    current period's scheduled instant has passed and we have not yet dispatched
    for that instant. This is robust to Celery Beat jitter (a tick landing a few
    seconds off the target minute no longer skips the whole day/week).
    """
    from datetime import timedelta

    try:
        hh, mm = schedule.time_utc.split(":")
        target_hour = int(hh)
        target_minute = int(mm)
    except (AttributeError, ValueError):
        logger.warning(f"Invalid time_utc for schedule {schedule.id}: {schedule.time_utc!r}")
        return False

    # Compute the most recent scheduled instant <= now for this schedule.
    if schedule.frequency == "daily":
        scheduled = now.replace(
            hour=target_hour, minute=target_minute, second=0, microsecond=0
        )
        if scheduled > now:
            scheduled -= timedelta(days=1)
    elif schedule.frequency == "weekly":
        if schedule.day_of_week is None:
            return False
        target_dow = int(schedule.day_of_week)  # 0=Monday..6=Sunday
        scheduled = now.replace(
            hour=target_hour, minute=target_minute, second=0, microsecond=0
        )
        # Walk back to the most recent occurrence of target_dow at/<= now.
        day_delta = (now.weekday() - target_dow) % 7
        scheduled -= timedelta(days=day_delta)
        if scheduled > now:
            scheduled -= timedelta(days=7)
    else:
        logger.warning(f"Unknown frequency for schedule {schedule.id}: {schedule.frequency!r}")
        return False

    # Already dispatched for this scheduled instant?
    last = schedule.last_run_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last >= scheduled:
            return False

    return True


async def _prune_old_backups(session, tenant_id: str, retention_count: int) -> list[str]:
    """Delete completed scheduled backups beyond the retention window."""
    from sqlalchemy import desc, select

    from src.core.admin_ops.domain.backup_job import BackupJob, BackupStatus
    from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient

    if retention_count is None or retention_count <= 0:
        return []

    result = await session.execute(
        select(BackupJob)
        .where(BackupJob.tenant_id == tenant_id)
        .where(BackupJob.is_scheduled.is_(True))
        .where(BackupJob.status == BackupStatus.COMPLETED)
        .order_by(desc(BackupJob.created_at))
    )
    rows = list(result.scalars().all())

    if len(rows) <= retention_count:
        return []

    to_prune = rows[retention_count:]
    pruned_ids: list[str] = []

    storage = MinIOClient()
    for job in to_prune:
        if job.result_path:
            try:
                storage.delete_file(job.result_path)
            except Exception as e:
                logger.warning(f"Could not delete backup file {job.result_path}: {e}")
        await session.delete(job)
        pruned_ids.append(job.id)

    await session.flush()
    return pruned_ids
