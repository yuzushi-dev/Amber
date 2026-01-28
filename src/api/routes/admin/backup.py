"""
Backup & Restore API
====================

Admin endpoints for system backup and restore operations.
"""

import io
import logging
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.admin_ops.domain.backup_job import (
    BackupJob, RestoreJob, BackupSchedule,
    BackupStatus, BackupScope, RestoreMode
)
from src.core.database import get_session_maker
from sqlalchemy import select, desc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["admin-backup"])


# ===== Schemas =====

class CreateBackupRequest(BaseModel):
    scope: str = "user_data"  # "user_data" or "full_system"


class CreateBackupResponse(BaseModel):
    job_id: str
    status: str
    message: str


class BackupJobResponse(BaseModel):
    id: str
    scope: str
    status: str
    progress: int
    file_size: Optional[int] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class BackupListResponse(BaseModel):
    backups: list[BackupJobResponse]
    total: int


class RestoreRequest(BaseModel):
    backup_id: Optional[str] = None  # Restore from existing backup
    mode: str = "merge"  # "merge" or "replace"


class RestoreResponse(BaseModel):
    job_id: str
    status: str
    message: str


class RestoreJobResponse(BaseModel):
    id: str
    mode: str
    status: str
    progress: int
    items_restored: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class ScheduleRequest(BaseModel):
    enabled: bool = True
    frequency: str = "daily"  # "daily" or "weekly"
    time_utc: str = "02:00"  # HH:MM
    day_of_week: Optional[int] = None  # 0-6 for weekly
    scope: str = "user_data"
    retention_count: int = 7


class ScheduleResponse(BaseModel):
    enabled: bool
    frequency: str
    time_utc: str
    day_of_week: Optional[int]
    scope: str
    retention_count: int
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None


# ===== Backup Endpoints =====

@router.post("/create", response_model=CreateBackupResponse)
async def create_backup(
    request: CreateBackupRequest,
    tenant_id: str = "default"
):
    """Start a new backup job."""
    from src.workers.backup_tasks import create_backup as create_backup_task
    
    # Validate scope
    try:
        scope = BackupScope(request.scope)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {request.scope}")
    
    job_id = str(uuid4())
    
    async with get_session_maker()() as session:
        # Create job record
        job = BackupJob(
            id=job_id,
            tenant_id=tenant_id,
            scope=scope,
            status=BackupStatus.PENDING
        )
        session.add(job)
        await session.commit()
    
    # Trigger Celery task
    create_backup_task.delay(job_id, tenant_id, request.scope)
    
    logger.info(f"Started backup job {job_id} for tenant {tenant_id}, scope={request.scope}")
    
    return CreateBackupResponse(
        job_id=job_id,
        status="pending",
        message="Backup job started"
    )


@router.get("/job/{job_id}", response_model=BackupJobResponse)
async def get_backup_job(job_id: str, tenant_id: str = "default"):
    """Get backup job status."""
    async with get_session_maker()() as session:
        result = await session.execute(
            select(BackupJob)
            .where(BackupJob.id == job_id)
            .where(BackupJob.tenant_id == tenant_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Backup job not found")
        
        return BackupJobResponse(
            id=job.id,
            scope=job.scope.value if job.scope else "user_data",
            status=job.status.value if job.status else "pending",
            progress=job.progress or 0,
            file_size=job.file_size,
            created_at=job.created_at.isoformat() if job.created_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            error_message=job.error_message
        )


@router.get("/job/{job_id}/download")
async def download_backup(job_id: str, tenant_id: str = "default"):
    """Download a completed backup file."""
    from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
    
    async with get_session_maker()() as session:
        result = await session.execute(
            select(BackupJob)
            .where(BackupJob.id == job_id)
            .where(BackupJob.tenant_id == tenant_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Backup job not found")
        
        if job.status != BackupStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Backup not ready for download")
        
        if not job.result_path:
            raise HTTPException(status_code=404, detail="Backup file not found")
    
    # Stream file from MinIO
    storage = MinIOClient()
    try:
        file_bytes = storage.get_file(job.result_path)
        
        filename = f"backup_{tenant_id}_{job_id[:8]}.zip"
        
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_bytes))
            }
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup file not found in storage")


@router.delete("/job/{job_id}")
async def delete_backup(job_id: str, tenant_id: str = "default"):
    """Delete a backup job and its file."""
    from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient
    
    async with get_session_maker()() as session:
        result = await session.execute(
            select(BackupJob)
            .where(BackupJob.id == job_id)
            .where(BackupJob.tenant_id == tenant_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Backup job not found")
        
        # Delete file from storage
        if job.result_path:
            try:
                storage = MinIOClient()
                storage.delete_file(job.result_path)
            except Exception as e:
                logger.warning(f"Could not delete backup file: {e}")
        
        # Delete job record
        await session.delete(job)
        await session.commit()
    
    return {"status": "deleted", "job_id": job_id}


@router.get("/list", response_model=BackupListResponse)
async def list_backups(
    tenant_id: str = "default",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100)
):
    """List available backups."""
    async with get_session_maker()() as session:
        # Get total count
        from sqlalchemy import func
        count_result = await session.execute(
            select(func.count())
            .select_from(BackupJob)
            .where(BackupJob.tenant_id == tenant_id)
        )
        total = count_result.scalar() or 0
        
        # Get backups
        result = await session.execute(
            select(BackupJob)
            .where(BackupJob.tenant_id == tenant_id)
            .order_by(desc(BackupJob.created_at))
            .offset((page - 1) * size)
            .limit(size)
        )
        jobs = result.scalars().all()
        
        backups = [
            BackupJobResponse(
                id=job.id,
                scope=job.scope.value if job.scope else "user_data",
                status=job.status.value if job.status else "pending",
                progress=job.progress or 0,
                file_size=job.file_size,
                created_at=job.created_at.isoformat() if job.created_at else None,
                completed_at=job.completed_at.isoformat() if job.completed_at else None,
                error_message=job.error_message
            )
            for job in jobs
        ]
        
        return BackupListResponse(backups=backups, total=total)


# ===== Restore Endpoints =====

@router.post("/restore", response_model=RestoreResponse)
async def start_restore(
    request: RestoreRequest,
    tenant_id: str = "default"
):
    """Start a restore job from a backup."""
    from src.workers.backup_tasks import restore_backup as restore_backup_task
    
    # Validate mode
    try:
        mode = RestoreMode(request.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")
    
    if not request.backup_id:
        raise HTTPException(status_code=400, detail="backup_id is required")
    
    # Find the backup
    async with get_session_maker()() as session:
        result = await session.execute(
            select(BackupJob)
            .where(BackupJob.id == request.backup_id)
            .where(BackupJob.tenant_id == tenant_id)
        )
        backup = result.scalar_one_or_none()
        
        if not backup:
            raise HTTPException(status_code=404, detail="Backup not found")
        
        if backup.status != BackupStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Backup is not ready")
        
        if not backup.result_path:
            raise HTTPException(status_code=400, detail="Backup file not found")
        
        # Create restore job
        job_id = str(uuid4())
        restore_job = RestoreJob(
            id=job_id,
            tenant_id=tenant_id,
            backup_job_id=request.backup_id,
            mode=mode,
            status=BackupStatus.PENDING
        )
        session.add(restore_job)
        await session.commit()
        
        backup_path = backup.result_path
    
    # Trigger Celery task
    restore_backup_task.delay(job_id, tenant_id, backup_path, request.mode)
    
    logger.info(f"Started restore job {job_id} from backup {request.backup_id}, mode={request.mode}")
    
    return RestoreResponse(
        job_id=job_id,
        status="pending",
        message="Restore job started"
    )


@router.get("/restore/{job_id}", response_model=RestoreJobResponse)
async def get_restore_job(job_id: str, tenant_id: str = "default"):
    """Get restore job status."""
    async with get_session_maker()() as session:
        result = await session.execute(
            select(RestoreJob)
            .where(RestoreJob.id == job_id)
            .where(RestoreJob.tenant_id == tenant_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Restore job not found")
        
        return RestoreJobResponse(
            id=job.id,
            mode=job.mode.value if job.mode else "merge",
            status=job.status.value if job.status else "pending",
            progress=job.progress or 0,
            items_restored=job.items_restored or 0,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            error_message=job.error_message
        )


# ===== Schedule Endpoints =====

@router.get("/schedule", response_model=ScheduleResponse)
async def get_schedule(tenant_id: str = "default"):
    """Get backup schedule configuration."""
    async with get_session_maker()() as session:
        result = await session.execute(
            select(BackupSchedule).where(BackupSchedule.tenant_id == tenant_id)
        )
        schedule = result.scalar_one_or_none()
        
        if not schedule:
            # Return default (disabled) schedule
            return ScheduleResponse(
                enabled=False,
                frequency="daily",
                time_utc="02:00",
                day_of_week=None,
                scope="user_data",
                retention_count=7
            )
        
        return ScheduleResponse(
            enabled=schedule.enabled == "true",
            frequency=schedule.frequency,
            time_utc=schedule.time_utc,
            day_of_week=schedule.day_of_week,
            scope=schedule.scope.value if schedule.scope else "user_data",
            retention_count=schedule.retention_count,
            last_run_at=schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            last_run_status=schedule.last_run_status
        )


@router.post("/schedule", response_model=ScheduleResponse)
async def set_schedule(
    request: ScheduleRequest,
    tenant_id: str = "default"
):
    """Configure backup schedule."""
    # Validate scope
    try:
        scope = BackupScope(request.scope)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {request.scope}")
    
    async with get_session_maker()() as session:
        result = await session.execute(
            select(BackupSchedule).where(BackupSchedule.tenant_id == tenant_id)
        )
        schedule = result.scalar_one_or_none()
        
        if schedule:
            # Update existing
            schedule.enabled = "true" if request.enabled else "false"
            schedule.frequency = request.frequency
            schedule.time_utc = request.time_utc
            schedule.day_of_week = request.day_of_week
            schedule.scope = scope
            schedule.retention_count = request.retention_count
        else:
            # Create new
            schedule = BackupSchedule(
                id=str(uuid4()),
                tenant_id=tenant_id,
                enabled="true" if request.enabled else "false",
                frequency=request.frequency,
                time_utc=request.time_utc,
                day_of_week=request.day_of_week,
                scope=scope,
                retention_count=request.retention_count
            )
            session.add(schedule)
        
        await session.commit()
        
        return ScheduleResponse(
            enabled=schedule.enabled == "true",
            frequency=schedule.frequency,
            time_utc=schedule.time_utc,
            day_of_week=schedule.day_of_week,
            scope=schedule.scope.value if schedule.scope else "user_data",
            retention_count=schedule.retention_count,
            last_run_at=schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            last_run_status=schedule.last_run_status
        )


@router.delete("/schedule")
async def delete_schedule(tenant_id: str = "default"):
    """Disable/delete backup schedule."""
    async with get_session_maker()() as session:
        result = await session.execute(
            select(BackupSchedule).where(BackupSchedule.tenant_id == tenant_id)
        )
        schedule = result.scalar_one_or_none()
        
        if schedule:
            schedule.enabled = "false"
            await session.commit()
    
    return {"status": "disabled"}
