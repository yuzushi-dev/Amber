"""
Embedding Administration
========================

Endpoints for managing embedding models, including compatibility checks and data migration.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.api.deps import get_db_session
from src.api.config import settings
from src.api.schemas.base import ResponseSchema
from src.core.admin_ops.application.migration_service import EmbeddingMigrationService
from src.core.ingestion.domain.document import Document
from src.core.state.machine import DocumentStatus
from src.infrastructure.adapters.celery_dispatcher import CeleryTaskDispatcher
from src.amber_platform.composition_root import platform, build_vector_store_factory

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

router = APIRouter(prefix="/embeddings", tags=["admin-embeddings"])

# In-memory migration state (could use Redis for multi-worker)
_migration_state: dict = {}

@router.get("/check", response_model=ResponseSchema[List[Any]])
async def check_embedding_compatibility(
    db: AsyncSession = Depends(get_db_session)
):
    """
    Check if the configured embedding model matches the stored data configuration for all tenants.
    """
    service = _get_migration_service(db)
    results = await service.get_compatibility_status()
    
    # Check if any mismatch exists to set overall message
    mismatch_count = sum(1 for r in results if not r["is_compatible"])
    msg = "All tenants compatible" if mismatch_count == 0 else f"Found {mismatch_count} incompatible tenants"
    
    return ResponseSchema(
        data=results,
        message=msg
    )

@router.post("/migrate", response_model=ResponseSchema[Any])
async def migrate_embeddings(
    tenant_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Trigger a destructive migration for a tenant.
    Drops current vector collection and triggers re-ingestion.
    """
    global _migration_state
    
    service = _get_migration_service(db)
    
    try:
        # Initialize migration state
        _migration_state[tenant_id] = {
            "status": "running",
            "phase": "preparing",
            "progress": 0,
            "message": "Preparing migration...",
            "total_docs": 0,
            "completed_docs": 0,
            "task_ids": [],
            "cancelled": False
        }
        
        result = await service.migrate_tenant(tenant_id)
        
        # Update state with doc count
        _migration_state[tenant_id].update({
            "phase": "Re-processing",
            "message": f"Re-processing {result['docs_queued']} documents...",
            "total_docs": result["docs_queued"],
            "completed_docs": 0,
            "task_ids": result.get("task_ids", []),
            "progress": 5  # Migration phase is ~5%
        })
        
        return ResponseSchema(
            data=result,
            message="Migration initiated successfully"
        )
    except ValueError as e:
        _migration_state.pop(tenant_id, None)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        _migration_state[tenant_id] = {
            "status": "failed",
            "phase": "error",
            "progress": 0,
            "message": str(e)
        }
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Migration failed: {str(e)}"
        )

@router.get("/migration-status", response_model=ResponseSchema[Any])
async def get_migration_status(
    tenant_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get the current migration and reprocessing status for a tenant.
    Progress tracks document re-processing from INGESTED -> READY.
    """
    global _migration_state
    
    state = _migration_state.get(tenant_id)
    
    if not state:
        return ResponseSchema(
            data={
                "status": "idle",
                "phase": "none",
                "progress": 100,
                "message": "No active migration"
            },
            message="No migration in progress"
        )
    
    # If cancelled, return cancelled state
    if state.get("cancelled"):
        return ResponseSchema(
            data={
                "status": "cancelled",
                "phase": "cancelled",
                "progress": state.get("progress", 0),
                "message": "Migration cancelled by user"
            },
            message="Migration was cancelled"
        )
    
    # Check document processing progress
    total_docs = state.get("total_docs", 0)
    
    # Handle zero-document case: migration is instant complete
    if total_docs == 0 and state.get("phase") == "Re-processing":
        state["status"] = "complete"
        state["phase"] = "complete"
        state["message"] = "Migration complete! No documents to re-process."
        state["progress"] = 100
    
    if total_docs > 0 and state.get("phase") == "Re-processing":
        # Count documents that are READY or beyond
        ready_query = select(func.count(Document.id)).where(
            Document.tenant_id == tenant_id,
                Document.status.in_([DocumentStatus.READY, DocumentStatus.EMBEDDING, DocumentStatus.GRAPH_SYNC, DocumentStatus.FAILED])
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
            # Clean up after a delay (or keep for UI to fetch)
        else:
            state["message"] = f"Re-processing documents: {completed}/{total_docs}"

        # Find currently processing document
        current_doc_query = select(Document.filename).where(
            Document.tenant_id == tenant_id,
            Document.status.in_([
                DocumentStatus.EXTRACTING,
                DocumentStatus.CLASSIFYING,
                DocumentStatus.CHUNKING,
                DocumentStatus.EMBEDDING,
                DocumentStatus.GRAPH_SYNC
            ])
        ).limit(1)
        
        current_doc = (await db.execute(current_doc_query)).scalar()
        if current_doc:
            state["current_document"] = current_doc

    
    return ResponseSchema(
        data={
            "status": state.get("status", "unknown"),
            "phase": state.get("phase", "unknown"),
            "progress": state.get("progress", 0),
            "message": state.get("message", ""),
            "total_docs": state.get("total_docs", 0),
            "completed_docs": state.get("completed_docs", 0),
            "current_document": state.get("current_document")
        },
        message="Status retrieved"
    )

@router.post("/cancel-migration", response_model=ResponseSchema[Any])
async def cancel_migration(
    tenant_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Cancel an in-progress migration.
    Note: This only stops tracking; already-queued documents will still process.
    """
    global _migration_state
    
    state = _migration_state.get(tenant_id)
    
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active migration found for this tenant"
        )
    
    if state.get("status") == "complete":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Migration already complete, cannot cancel"
        )
    
    state["cancelled"] = True
    state["status"] = "cancelled"
    state["message"] = "Migration cancelled by user. Stopping worker tasks..."
    
    # Revoke all tasks in worker
    service = _get_migration_service(db)
    await service.cancel_tenant_migration(state.get("task_ids", []))
    
    return ResponseSchema(
        data={"cancelled": True},
        message="Migration cancelled"
    )
