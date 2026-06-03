"""
Embedding Administration
========================

Endpoints for managing embedding models, including compatibility checks and data migration.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.amber_platform.composition_root import build_vector_store_factory, platform
from src.api.config import settings
from src.api.deps import get_db_session, verify_super_admin
from src.api.schemas.base import ResponseSchema
from src.core.admin_ops.application.migration_service import EmbeddingMigrationService
from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus
from src.infrastructure.adapters.celery_dispatcher import CeleryTaskDispatcher

logger = logging.getLogger(__name__)

# Redis key pattern: embedding_migration:{tenant_id}
# TTL: 7 days (enough to survive any reasonable migration + polling window)
_MIGRATION_KEY_PREFIX = "embedding_migration"
_MIGRATION_TTL_SECONDS = 7 * 24 * 3600


def _migration_redis_key(tenant_id: str) -> str:
    return f"{_MIGRATION_KEY_PREFIX}:{tenant_id}"


async def _redis_get_state(tenant_id: str) -> dict | None:
    """Read migration state from Redis. Returns None if missing or Redis unavailable."""
    try:
        import redis.asyncio as redis_async

        r = redis_async.from_url(settings.db.redis_url, decode_responses=True)
        try:
            raw = await r.get(_migration_redis_key(tenant_id))
            return json.loads(raw) if raw else None
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning(f"Redis read failed for migration state ({tenant_id}): {exc}")
        return None


async def _redis_set_state(tenant_id: str, state: dict) -> None:
    """Write migration state to Redis with TTL. Best-effort; never raises."""
    try:
        import redis.asyncio as redis_async

        r = redis_async.from_url(settings.db.redis_url, decode_responses=True)
        try:
            await r.setex(
                _migration_redis_key(tenant_id),
                _MIGRATION_TTL_SECONDS,
                json.dumps(state, default=str),
            )
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning(f"Redis write failed for migration state ({tenant_id}): {exc}")


async def _redis_delete_state(tenant_id: str) -> None:
    """Delete migration state from Redis. Best-effort; never raises."""
    try:
        import redis.asyncio as redis_async

        r = redis_async.from_url(settings.db.redis_url, decode_responses=True)
        try:
            await r.delete(_migration_redis_key(tenant_id))
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning(f"Redis delete failed for migration state ({tenant_id}): {exc}")


def _get_migration_service(db: AsyncSession) -> EmbeddingMigrationService:
    """Factory to create EmbeddingMigrationService with all deps."""
    vector_store_factory = build_vector_store_factory()
    return EmbeddingMigrationService(
        session=db,
        settings=settings,
        task_dispatcher=CeleryTaskDispatcher(),
        graph_client=platform.neo4j_client,
        vector_store_factory=vector_store_factory,
    )


router = APIRouter(prefix="/embeddings", tags=["admin-embeddings"], dependencies=[Depends(verify_super_admin)])


@router.get("/check", response_model=ResponseSchema[list[Any]])
async def check_embedding_compatibility(db: AsyncSession = Depends(get_db_session)):
    """
    Check if the configured embedding model matches the stored data configuration for all tenants.
    """
    service = _get_migration_service(db)
    results = await service.get_compatibility_status()

    # Check if any mismatch exists to set overall message
    mismatch_count = sum(1 for r in results if not r["is_compatible"])
    msg = (
        "All tenants compatible"
        if mismatch_count == 0
        else f"Found {mismatch_count} incompatible tenants"
    )

    return ResponseSchema(data=results, message=msg)


@router.post("/migrate", response_model=ResponseSchema[Any])
async def migrate_embeddings(tenant_id: str, db: AsyncSession = Depends(get_db_session)):
    """
    Trigger a destructive in-place migration for a tenant.

    Drops the tenant's active vector collection (resolved via active_vector_collection
    config, not hardcoded) and triggers re-ingestion of all documents.

    Migration progress is stored in Redis (embedding_migration:{tenant_id}) so it
    survives API restarts and is consistent across multiple API replicas.
    """
    initial_state: dict[str, Any] = {
        "status": "running",
        "phase": "preparing",
        "progress": 0,
        "message": "Preparing migration...",
        "total_docs": 0,
        "completed_docs": 0,
        "task_ids": [],
        "cancelled": False,
    }
    await _redis_set_state(tenant_id, initial_state)

    service = _get_migration_service(db)

    try:
        result = await service.migrate_tenant(tenant_id)

        running_state: dict[str, Any] = {
            **initial_state,
            "phase": "Re-processing",
            "message": f"Re-processing {result['docs_queued']} documents...",
            "total_docs": result["docs_queued"],
            "completed_docs": 0,
            "task_ids": result.get("task_ids", []),
            "progress": 5,  # Migration phase is ~5%
        }
        await _redis_set_state(tenant_id, running_state)

        logger.info(
            f"Migration initiated for tenant {tenant_id}: "
            f"{result['docs_queued']} docs queued for re-ingestion"
        )
        return ResponseSchema(data=result, message="Migration initiated successfully")
    except ValueError as e:
        await _redis_delete_state(tenant_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        error_state: dict[str, Any] = {
            "status": "failed",
            "phase": "error",
            "progress": 0,
            "message": str(e),
        }
        await _redis_set_state(tenant_id, error_state)
        logger.error(f"Migration failed for tenant {tenant_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error"
        ) from e


@router.get("/migration-status", response_model=ResponseSchema[Any])
async def get_migration_status(tenant_id: str, db: AsyncSession = Depends(get_db_session)):
    """
    Get the current migration and reprocessing status for a tenant.
    Progress tracks document re-processing from INGESTED -> READY.
    State is read from Redis so it is consistent across API replicas and restarts.
    """
    state = await _redis_get_state(tenant_id)

    if not state:
        return ResponseSchema(
            data={
                "status": "idle",
                "phase": "none",
                "progress": 100,
                "message": "No active migration",
            },
            message="No migration in progress",
        )

    # If cancelled, return cancelled state
    if state.get("cancelled"):
        return ResponseSchema(
            data={
                "status": "cancelled",
                "phase": "cancelled",
                "progress": state.get("progress", 0),
                "message": "Migration cancelled by user",
            },
            message="Migration was cancelled",
        )

    # Check document processing progress
    total_docs = state.get("total_docs", 0)

    # Handle zero-document case: migration is instant complete
    if total_docs == 0 and state.get("phase") == "Re-processing":
        state["status"] = "complete"
        state["phase"] = "complete"
        state["message"] = "Migration complete! No documents to re-process."
        state["progress"] = 100
        await _redis_set_state(tenant_id, state)

    if total_docs > 0 and state.get("phase") == "Re-processing":
        # Count documents that are READY or beyond
        ready_query = select(func.count(Document.id)).where(
            Document.tenant_id == tenant_id,
            Document.status.in_(
                [
                    DocumentStatus.READY,
                    DocumentStatus.EMBEDDING,
                    DocumentStatus.GRAPH_SYNC,
                    DocumentStatus.FAILED,
                ]
            ),
        )
        completed = (await db.execute(ready_query)).scalar() or 0

        # Calculate progress (5% for migration, 95% for reprocessing)
        reprocess_progress = (completed / total_docs) * 95 if total_docs > 0 else 0
        total_progress = min(5 + reprocess_progress, 100)

        state["completed_docs"] = completed
        state["progress"] = int(total_progress)

        if completed >= total_docs:
            state["status"] = "complete"
            state["phase"] = "complete"
            state["message"] = f"Migration complete! All {total_docs} documents re-processed."
            state["progress"] = 100
        else:
            state["message"] = f"Re-processing documents: {completed}/{total_docs}"

        # Find currently processing document
        current_doc_query = (
            select(Document.filename)
            .where(
                Document.tenant_id == tenant_id,
                Document.status.in_(
                    [
                        DocumentStatus.EXTRACTING,
                        DocumentStatus.CLASSIFYING,
                        DocumentStatus.CHUNKING,
                        DocumentStatus.EMBEDDING,
                        DocumentStatus.GRAPH_SYNC,
                    ]
                ),
            )
            .limit(1)
        )

        current_doc = (await db.execute(current_doc_query)).scalar()
        if current_doc:
            state["current_document"] = current_doc

        # Persist updated progress back to Redis
        await _redis_set_state(tenant_id, state)

    return ResponseSchema(
        data={
            "status": state.get("status", "unknown"),
            "phase": state.get("phase", "unknown"),
            "progress": state.get("progress", 0),
            "message": state.get("message", ""),
            "total_docs": state.get("total_docs", 0),
            "completed_docs": state.get("completed_docs", 0),
            "current_document": state.get("current_document"),
        },
        message="Status retrieved",
    )


@router.post("/cancel-migration", response_model=ResponseSchema[Any])
async def cancel_migration(tenant_id: str, db: AsyncSession = Depends(get_db_session)):
    """
    Cancel an in-progress migration.
    Note: This only stops tracking; already-queued documents will still process.
    Cancellation state is written to Redis so all API replicas see it.
    """
    state = await _redis_get_state(tenant_id)

    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active migration found for this tenant",
        )

    if state.get("status") == "complete":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Migration already complete, cannot cancel",
        )

    state["cancelled"] = True
    state["status"] = "cancelled"
    state["message"] = "Migration cancelled by user. Stopping worker tasks..."
    await _redis_set_state(tenant_id, state)

    # Revoke all tasks in worker
    service = _get_migration_service(db)
    await service.cancel_tenant_migration(state.get("task_ids", []))

    logger.info(f"Migration cancelled for tenant {tenant_id}")
    return ResponseSchema(data={"cancelled": True}, message="Migration cancelled")
