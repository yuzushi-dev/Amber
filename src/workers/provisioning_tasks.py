"""
Provisioning Background Tasks
==============================

Celery task for cloning tenant data (documents + vectors) without
re-running the ingestion pipeline.
"""

import logging

from src.workers.celery_app import celery_app
from src.workers.tasks import BaseTask, run_async

logger = logging.getLogger(__name__)


def _publish_provisioning_status(job_id: str, status: str, progress: int, error: str = None):
    """Publish provisioning status to Redis Pub/Sub."""
    import json

    try:
        import redis

        from src.api.config import settings

        r = redis.Redis.from_url(settings.db.redis_url)
        try:
            channel = f"provisioning:{job_id}:status"
            message = {"job_id": job_id, "status": status, "progress": progress}
            if error:
                message["error"] = error
            r.publish(channel, json.dumps(message))
        finally:
            r.close()
    except Exception as e:
        logger.warning(f"Failed to publish provisioning status: {e}")


@celery_app.task(
    bind=True,
    name="src.workers.provisioning_tasks.provision_tenant",
    base=BaseTask,
    max_retries=1,   # not idempotent — do not auto-retry
    queue="low_priority",
)
def provision_tenant(self, job_id: str) -> dict:
    """Celery task entry point.  Wraps the async implementation."""
    try:
        result = run_async(_provision_async(job_id, self.request.id))
        return result
    except Exception as e:
        logger.error(f"Provisioning task {job_id} failed: {e}", exc_info=True)
        run_async(_mark_provision_failed(job_id, str(e)))
        raise


async def _provision_async(job_id: str, task_id: str) -> dict:
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.workers.tasks import deep_reset_singletons

    deep_reset_singletons()

    from src.api.config import settings
    from src.amber_platform.composition_root import build_vector_store_factory, platform
    from src.core.admin_ops.domain.provisioning_job import ProvisioningJob, ProvisioningStatus
    from src.core.admin_ops.application.provisioning_service import ProvisioningService

    engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)
    try:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            from src.core.database.session import configure_worker_session
            await configure_worker_session(session)

            # Load the job row
            result = await session.execute(
                select(ProvisioningJob).where(ProvisioningJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                raise ValueError(f"ProvisioningJob {job_id!r} not found")

            job.status = ProvisioningStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await session.commit()
            _publish_provisioning_status(job_id, "running", 5)

            service = ProvisioningService(
                session=session,
                vector_store_factory=build_vector_store_factory(),
                neo4j_client=platform.neo4j_client,
            )

            def _progress(pct: int):
                job.progress = pct
                _publish_provisioning_status(job_id, "running", pct)

            result_data = await service.provision(job_id, progress_callback=_progress)

            job.status = ProvisioningStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.progress = 100
            job.docs_copied = result_data.get("docs_copied", 0)
            job.chunks_copied = result_data.get("chunks_copied", 0)
            job.vectors_copied = result_data.get("vectors_copied", 0)
            job.graph_nodes_copied = result_data.get("graph_nodes_copied", 0)
            await session.commit()

            _publish_provisioning_status(job_id, "completed", 100)
            return {**result_data, "job_id": job_id, "task_id": task_id}
    finally:
        await engine.dispose()


async def _mark_provision_failed(job_id: str, error: str):
    """Update job status to FAILED; best-effort (swallows its own errors)."""
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.config import settings
    from src.core.admin_ops.domain.provisioning_job import ProvisioningJob, ProvisioningStatus

    try:
        engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)
        try:
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as session:
                from src.core.database.session import configure_worker_session
                await configure_worker_session(session)
                result = await session.execute(
                    select(ProvisioningJob).where(ProvisioningJob.id == job_id)
                )
                job = result.scalar_one_or_none()
                if job:
                    job.status = ProvisioningStatus.FAILED
                    job.completed_at = datetime.now(UTC)
                    job.error_message = error[:2000]
                    await session.commit()
        finally:
            await engine.dispose()
        _publish_provisioning_status(job_id, "failed", job.progress if job else 0, error=error)
    except Exception as e:
        logger.error(f"Failed to mark provisioning job {job_id} as failed: {e}")
