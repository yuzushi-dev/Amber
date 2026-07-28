"""
Stale Document Recovery
=======================

Handles recovery of documents stuck in processing states after worker restart.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# Minimum age a document must have before a sweep may touch it.
#
# This is a safety floor, not a tuning knob, and it applies at worker boot too.
# The boot sweep used to run with no threshold on the reasoning that nothing is
# in-flight at startup — true with a single worker, false since
# docker-compose.yml declares `replicas: 3`. One replica restarting (a deploy, or
# an OOM-kill against its 2G cap) would otherwise sweep documents the other two
# are actively processing: EXTRACTING/CLASSIFYING get marked FAILED, and
# EMBEDDING/GRAPH_SYNC get reset to INGESTED and requeued while the original task
# is still running under task_acks_late. The requeued run then executes the
# destructive pre-ingest cleanup (Milvus delete_by_document, Neo4j DETACH DELETE)
# concurrently with the original run's writes, leaving a partial vector set.
#
# 30 minutes covers the longest observed stage (graph-sync).
#
# ponytail: there is no per-document heartbeat, so updated_at only advances at
# stage transitions and a single stage running longer than this floor can still
# be swept. If that starts happening, write a heartbeat from the pipeline instead
# of raising the floor.
STALE_MIN_AGE_MINUTES = 30


async def recover_stale_documents(min_age_minutes: int = STALE_MIN_AGE_MINUTES) -> dict[str, Any]:
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

    Args:
        min_age_minutes: Only recover documents whose updated_at is older than
            this many minutes.  Defaults to STALE_MIN_AGE_MINUTES, which every
            caller should keep: it is what stops a sweep from resetting and
            requeueing a document another worker replica is processing right now.
            Pass 0 only from a context that has proven no worker is running.

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
        DocumentStatus.INGESTED,
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
                stale_query = (
                    select(Document)
                    .where(Document.status.in_(STALE_STATES))
                )
                # Age threshold: skip documents updated recently so no sweep -
                # periodic or boot-time - resets a document that is legitimately
                # in-flight on this or another replica.  See
                # STALE_MIN_AGE_MINUTES.  SKIP LOCKED below only serialises
                # concurrent sweeps; it does not protect a document from a sweep
                # while a worker is mid-pipeline on it, because the pipeline
                # commits between stages and holds no row lock across them.
                if min_age_minutes > 0:
                    cutoff = datetime.now(UTC) - timedelta(minutes=min_age_minutes)
                    stale_query = stale_query.where(Document.updated_at < cutoff)
                # Batch limit: without this, the first sweep after deploy (or after
                # any long outage) could dispatch every stale document at once -
                # e.g. up to 67 INGESTED documents rediscovered by this recovery
                # sweep in one run. Cap it so reprocessing bursts stay bounded;
                # documents left over are picked up by the next sweep.
                stale_query = stale_query.limit(50)
                stale_query = stale_query.with_for_update(skip_locked=True)
                result = await session.execute(stale_query)
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
                        elif original_status == DocumentStatus.INGESTED:
                            # Document never picked up by a worker (or was requeued by
                            # a prior sweep and stalled again): it is already in the
                            # exact state process_document's optimistic guard expects
                            # (old_status=INGESTED), so just requeue it - do NOT reset
                            # document.status, unlike REQUEUE_STATES above where a reset
                            # is needed to get back to INGESTED in the first place.
                            requeue.append((document.id, document.tenant_id))
                            recovered += 1
                            logger.info(
                                f"Requeued document {document.id} ({document.filename}) for "
                                "reprocess (was stuck in INGESTED)"
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


def run_recovery_sync(min_age_minutes: int = STALE_MIN_AGE_MINUTES) -> dict[str, Any]:
    """
    Synchronous wrapper for recovery function.
    Used by Celery signals which run in sync context.

    Args:
        min_age_minutes: Forwarded to recover_stale_documents.  The default is
            the safety floor; the worker_ready signal relies on it, so do not
            reintroduce a 0 default here.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(recover_stale_documents(min_age_minutes=min_age_minutes))
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
    # Age threshold comes from STALE_MIN_AGE_MINUTES, shared with the boot-time
    # path so the two cannot drift apart.
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
