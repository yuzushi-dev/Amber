"""
Stale Document Recovery
=======================

Handles recovery of documents stuck in processing states after worker restart.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
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
    from src.core.ingestion.domain.chunk import Chunk
    from src.core.ingestion.domain.document import Document
    from src.core.state.machine import DocumentStatus

    # Processing states that indicate incomplete work
    STALE_STATES = [
        DocumentStatus.EXTRACTING,
        DocumentStatus.CLASSIFYING,
        DocumentStatus.CHUNKING,
        DocumentStatus.EMBEDDING,
        DocumentStatus.GRAPH_SYNC,
    ]
    # States where chunks already exist but downstream (embedding / graph sync)
    # was interrupted. These are requeued for a full, idempotent reprocess
    # (chunk ids are deterministic, so no duplicates) instead of being failed.
    REQUEUE_STATES = [
        DocumentStatus.EMBEDDING,
        DocumentStatus.GRAPH_SYNC,
    ]

    logger.info("Starting stale document recovery check...")

    try:
        # Create async session
        engine = create_async_engine(settings.db.app_database_url or settings.db.database_url)

        try:
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            recovered = 0
            failed = 0
            total = 0

            async with async_session() as session:
                from src.core.database.session import configure_worker_session
                await configure_worker_session(session)
                # Find all documents in stale states
                # Fix: Use SKIP LOCKED to prevent race conditions between multiple workers
                result = await session.execute(
                    select(Document)
                    .where(Document.status.in_(STALE_STATES))
                    .with_for_update(skip_locked=True)
                )
                stale_documents = result.scalars().all()
                total = len(stale_documents)

                if total == 0:
                    logger.info("No stale documents found")
                    return {"recovered": 0, "failed": 0, "total": 0}

                logger.info(f"Found {total} stale document(s) to process")

                requeue: list[tuple[str, str]] = []  # (document_id, tenant_id) dispatched after commit

                for document in stale_documents:
                    try:
                        # Check if document has chunks
                        chunk_result = await session.execute(
                            select(Chunk).where(Chunk.document_id == document.id).limit(1)
                        )
                        has_chunks = chunk_result.scalars().first() is not None

                        original_status = document.status

                        if document.status == DocumentStatus.CHUNKING and has_chunks:
                            # Document was in final stage with chunks - likely completed
                            document.status = DocumentStatus.READY
                            document.updated_at = datetime.now(UTC)
                            recovered += 1
                            logger.info(
                                f"Recovered document {document.id} ({document.filename}) -> READY"
                            )
                        elif original_status in REQUEUE_STATES:
                            # Embedding / graph-sync interrupted: reset to INGESTED so the
                            # pipeline's optimistic guard (old_status=INGESTED) lets it rerun,
                            # then requeue a full reprocess after commit. Deterministic chunk
                            # ids make the rerun idempotent (overwrite, no duplicates).
                            document.status = DocumentStatus.INGESTED
                            document.updated_at = datetime.now(UTC)
                            document.error_message = None
                            requeue.append((document.id, document.tenant_id))
                            recovered += 1
                            logger.info(
                                f"Requeued document {document.id} ({document.filename}) for reprocess "
                                f"(was in {getattr(original_status, 'value', original_status)} state)"
                            )
                            _publish_recovery_status(document.id, document.status.value)
                            continue
                        else:
                            # Document was interrupted before completion - mark as failed
                            document.status = DocumentStatus.FAILED
                            document.updated_at = datetime.now(UTC)
                            document.error_message = (
                                "Processing interrupted by worker restart. "
                                f"Previous state: {getattr(original_status, 'value', original_status)}. "
                                "Please retry document upload."
                            )
                            failed += 1
                            logger.warning(
                                f"Marked document {document.id} ({document.filename}) as FAILED "
                                f"(was in {getattr(original_status, 'value', original_status)} state)"
                            )

                        # Publish status update via Redis
                        _publish_recovery_status(document.id, document.status.value)

                    except Exception as e:
                        logger.error(f"Error processing stale document {document.id}: {e}")
                        failed += 1

                # Commit all changes
                await session.commit()

            # After the status reset is committed, dispatch reprocess tasks.
            # Local import avoids a circular import (tasks -> recovery at worker boot).
            if requeue:
                from src.workers.tasks import process_document

                for doc_id, tid in requeue:
                    try:
                        process_document.delay(doc_id, tid)
                        logger.info(f"Dispatched reprocess for {doc_id}")
                    except Exception as e:
                        logger.error(f"Failed to dispatch reprocess for {doc_id}: {e}")

        finally:
            # Fix: Ensure engine is disposed to prevent resource leaks
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
            "message": f"Document status updated by recovery process to: {status}",
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


# ---------------------------------------------------------------------------
# Periodic recovery task
# ---------------------------------------------------------------------------
# Registered in celery_app.beat_schedule so Celery Beat dispatches it on a
# regular interval (default every 10 minutes).  The task simply delegates to
# run_recovery_sync so the actual recovery logic lives in one place.
#
# Import of celery_app is deferred to inside the function to avoid the
# circular import that would arise from importing it at module level
# (celery_app -> include[tasks] -> tasks -> recovery -> celery_app).


def _get_celery_app():
    """Lazy import of celery_app to break the circular-import cycle."""
    from src.workers.celery_app import celery_app as _app  # noqa: PLC0415

    return _app


# Build the task using a lazy-binding pattern so we don't import celery_app at
# module load time.  The shared_task decorator from Celery achieves exactly
# this: it binds to whatever app is active at call time rather than at import
# time.
from celery import shared_task  # noqa: E402


@shared_task(
    name="src.workers.recovery.periodic_recovery_sweep",
    bind=False,
    ignore_result=True,
    # Prevent overlapping runs if a sweep takes longer than the interval.
    # Requires the celery-redbeat or django-celery-beat lock backend; for the
    # built-in scheduler this is advisory only.
    acks_late=True,
)
def periodic_recovery_sweep() -> dict[str, Any]:
    """
    Periodic Celery Beat task: recover documents stuck in processing states.

    Runs on the beat_schedule interval (default every 10 minutes).  Delegates
    entirely to ``run_recovery_sync`` so the recovery logic is not duplicated.
    Idempotent and tenant-agnostic (queries all documents across all tenants).
    """
    logger.info("Periodic recovery sweep triggered by Celery Beat")
    result = run_recovery_sync()
    if result.get("total", 0) > 0:
        logger.info(
            "Periodic recovery sweep: %(recovered)s recovered, %(failed)s failed, "
            "%(total)s total",
            result,
        )
    else:
        logger.debug("Periodic recovery sweep: no stale documents found")
    return result
