"""
Export API Routes
=================

Endpoints for exporting conversation data.
"""

import logging
from datetime import datetime, UTC
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, get_current_tenant_id
from src.core.admin_ops.domain.export_job import ExportJob, ExportStatus
from src.core.generation.domain.memory_models import ConversationSummary
from src.amber_platform.composition_root import platform
from src.core.admin_ops.application.export_service import ExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


# =============================================================================
# Response Models
# =============================================================================

class ExportJobResponse(BaseModel):
    """Response for export job creation/status."""
    job_id: str
    status: str
    progress: int | None = None
    download_url: str | None = None
    file_size: int | None = None
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class StartExportResponse(BaseModel):
    """Response when starting a bulk export."""
    job_id: str
    status: str
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/conversation/{conversation_id}")
async def export_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Export a single conversation as a ZIP file.
    
    The ZIP contains:
    - transcript.txt: Human-readable conversation text
    - metadata.json: Chunks and document references
    - documents/: Referenced source documents
    
    This is a synchronous operation - the ZIP is generated and streamed directly.
    """
    # Verify conversation exists and belongs to tenant
    result = await session.execute(
        select(ConversationSummary)
        .where(ConversationSummary.id == conversation_id)
        .where(ConversationSummary.tenant_id == tenant_id)
    )
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    try:
        storage = platform.minio_client
        export_service = ExportService(session, storage)
        
        zip_bytes = await export_service.generate_single_conversation_zip(conversation_id)
        
        # Generate filename
        safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in conversation.title[:30])
        filename = f"conversation_{safe_title}_{conversation_id[:8]}.zip"
        
        return StreamingResponse(
            iter([zip_bytes]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(zip_bytes)),
            }
        )
    except Exception as e:
        logger.error(f"Failed to export conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.post("/all", response_model=StartExportResponse)
async def start_export_all(
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Start an async job to export all conversations.
    
    This creates a background job that will:
    1. Generate a ZIP containing all conversations
    2. Upload it to storage
    3. Make it available for download
    
    Poll /export/job/{job_id} to check status and get download URL.
    """
    from src.workers.export_tasks import export_all_conversations
    
    # Create export job
    job_id = str(uuid4())
    job = ExportJob(
        id=job_id,
        tenant_id=tenant_id,
        status=ExportStatus.PENDING,
    )
    session.add(job)
    await session.commit()
    
    # Dispatch Celery task
    try:
        # Use job_id as task_id to allow easy revocation
        export_all_conversations.apply_async(args=[job_id, tenant_id], task_id=job_id)
        logger.info(f"Dispatched export job {job_id} for tenant {tenant_id}")
    except Exception as e:
        # Update job status to failed
        job.status = ExportStatus.FAILED
        job.error_message = f"Failed to dispatch task: {str(e)}"
        await session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start export: {str(e)}")
    
    return StartExportResponse(
        job_id=job_id,
        status="pending",
        message="Export job started. Poll /export/job/{job_id} for status."
    )


@router.get("/job/{job_id}", response_model=ExportJobResponse)
async def get_export_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Get the status of an export job.
    
    Returns current status, and if completed, includes download URL.
    """
    result = await session.execute(
        select(ExportJob)
        .where(ExportJob.id == job_id)
        .where(ExportJob.tenant_id == tenant_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    
    response = ExportJobResponse(
        job_id=job.id,
        status=job.status.value,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error=job.error_message,
    )
    
    if job.status == ExportStatus.COMPLETED and job.result_path:
        response.download_url = f"/api/v1/export/job/{job_id}/download"
        if job.file_size:
            response.file_size = int(job.file_size)
    
    return response


@router.get("/job/{job_id}/download")
async def download_export(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Download the completed export ZIP.
    
    Only available after job status is 'completed'.
    """
    result = await session.execute(
        select(ExportJob)
        .where(ExportJob.id == job_id)
        .where(ExportJob.tenant_id == tenant_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    
    if job.status != ExportStatus.COMPLETED:
        raise HTTPException(
            status_code=400, 
            detail=f"Export not ready. Current status: {job.status.value}"
        )
    
    if not job.result_path:
        raise HTTPException(status_code=500, detail="Export completed but no file found")
    
    try:
        storage = platform.minio_client
        file_bytes = storage.get_file(job.result_path)
        
        filename = f"amber_export_{job_id[:8]}.zip"
        
        return StreamingResponse(
            iter([file_bytes]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_bytes)),
            }
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Export file not found in storage")
    except Exception as e:
        logger.error(f"Failed to download export {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.delete("/job/{job_id}")
async def cancel_export_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Cancel or delete an export job.
    
    - For pending/running jobs: marks as cancelled
    - For completed jobs: deletes the job record and any stored files
    - For failed jobs: deletes the job record
    """
    result = await session.execute(
        select(ExportJob)
        .where(ExportJob.id == job_id)
        .where(ExportJob.tenant_id == tenant_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    
    # If job has a result file, try to delete it
    if job.result_path:
        try:
            storage = platform.minio_client
            storage.delete_file(job.result_path)
            logger.info(f"Deleted export file: {job.result_path}")
        except Exception as e:
            logger.warning(f"Failed to delete export file {job.result_path}: {e}")
    
    # If job is running, try to revoke the Celery task
    if job.status in (ExportStatus.PENDING, ExportStatus.RUNNING):
        try:
            from src.workers.celery_app import celery_app
            celery_app.control.revoke(job_id, terminate=True)
            logger.info(f"Revoked Celery task for job {job_id}")
        except Exception as e:
            logger.warning(f"Failed to revoke Celery task {job_id}: {e}")
    
    # Delete the job record
    await session.delete(job)
    await session.commit()
    
    return {"status": "cancelled", "message": f"Export job {job_id} cancelled and deleted"}
