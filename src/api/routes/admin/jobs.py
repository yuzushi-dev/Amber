"""
Job Management API
==================

Admin endpoints for monitoring and controlling Celery background tasks.

Stage 10.1 - Pipeline Control Dashboard Backend
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["admin-jobs"])


# =============================================================================
# Schemas
# =============================================================================

class JobStatus(str, Enum):
    """Celery task states."""
    PENDING = "PENDING"
    STARTED = "STARTED"
    PROGRESS = "PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    REVOKED = "REVOKED"
    RETRY = "RETRY"


class JobInfo(BaseModel):
    """Job information response."""
    task_id: str
    task_name: Optional[str] = None
    status: str
    progress: Optional[int] = Field(None, ge=0, le=100)
    progress_message: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    runtime_seconds: Optional[float] = None
    retries: int = 0
    

class JobListResponse(BaseModel):
    """List of jobs response."""
    jobs: List[JobInfo]
    total: int
    active_count: int
    reserved_count: int


class QueueInfo(BaseModel):
    """Queue status information."""
    queue_name: str
    message_count: int
    consumer_count: int


class WorkerInfo(BaseModel):
    """Worker status information."""
    hostname: str
    status: str
    active_tasks: int
    processed_total: int
    concurrency: int
    queues: List[str]


class QueuesResponse(BaseModel):
    """Queue and worker status response."""
    queues: List[QueueInfo]
    workers: List[WorkerInfo]
    total_active_tasks: int


class CancelResponse(BaseModel):
    """Cancel task response."""
    task_id: str
    status: str
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
    task_type: Optional[str] = Query(None, description="Filter by task type (e.g., 'process_document')"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
):
    """
    List active and recent Celery tasks.
    
    Returns a list of tasks with their current status, progress, and metadata.
    """
    try:
        # Get active tasks from all workers
        inspect = celery_app.control.inspect()
        
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        scheduled = inspect.scheduled() or {}
        
        jobs = []
        active_count = 0
        reserved_count = 0
        
        # Process active tasks
        for worker, tasks in active.items():
            active_count += len(tasks)
            for task in tasks:
                job_info = _task_to_job_info(task, "STARTED")
                if _matches_filters(job_info, status, task_type):
                    jobs.append(job_info)
        
        # Process reserved (queued) tasks
        for worker, tasks in reserved.items():
            reserved_count += len(tasks)
            for task in tasks:
                job_info = _task_to_job_info(task, "PENDING")
                if _matches_filters(job_info, status, task_type):
                    jobs.append(job_info)
        
        # Process scheduled tasks
        for worker, tasks in scheduled.items():
            for task in tasks:
                job_info = _task_to_job_info(task.get("request", task), "PENDING")
                if _matches_filters(job_info, status, task_type):
                    jobs.append(job_info)
        
        # Limit results
        jobs = jobs[:limit]
        
        return JobListResponse(
            jobs=jobs,
            total=len(jobs),
            active_count=active_count,
            reserved_count=reserved_count,
        )
        
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


@router.get("/{task_id}", response_model=JobInfo)
async def get_job(task_id: str):
    """
    Get detailed information about a specific task.
    
    Returns the task's current status, progress, result, or error.
    """
    try:
        result = celery_app.AsyncResult(task_id)
        
        # Get task info from meta
        info = result.info or {}
        
        job_info = JobInfo(
            task_id=task_id,
            task_name=result.name,
            status=result.status,
            progress=info.get("progress") if isinstance(info, dict) else None,
            progress_message=info.get("message") if isinstance(info, dict) else None,
            result=result.result if result.successful() else None,
            error=str(result.result) if result.failed() else None,
            started_at=info.get("started_at") if isinstance(info, dict) else None,
            completed_at=result.date_done,
            retries=info.get("retries", 0) if isinstance(info, dict) else 0,
        )
        
        # Calculate runtime if we have start time
        if job_info.started_at:
            end_time = job_info.completed_at or datetime.now(timezone.utc)
            if isinstance(job_info.started_at, str):
                start = datetime.fromisoformat(job_info.started_at.replace('Z', '+00:00'))
            else:
                start = job_info.started_at
            job_info.runtime_seconds = (end_time - start).total_seconds()
        
        return job_info
        
    except Exception as e:
        logger.error(f"Failed to get job {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get job: {str(e)}")


@router.post("/{task_id}/cancel", response_model=CancelResponse)
async def cancel_job(task_id: str, terminate: bool = Query(False, description="Force terminate if running")):
    """
    Cancel or revoke a task.
    
    - For pending tasks: Removes from queue
    - For running tasks: Sends revoke signal (use terminate=True to force kill)
    """
    try:
        result = celery_app.AsyncResult(task_id)
        current_status = result.status
        
        if current_status in ["SUCCESS", "FAILURE", "REVOKED"]:
            return CancelResponse(
                task_id=task_id,
                status=current_status,
                message=f"Task already in terminal state: {current_status}"
            )
        
        # Revoke the task
        celery_app.control.revoke(task_id, terminate=terminate, signal='SIGTERM')
        
        message = "Task revoked"
        if terminate:
            message = "Task terminated (SIGTERM sent)"
        
        logger.info(f"Cancelled task {task_id}, terminate={terminate}")
        
        return CancelResponse(
            task_id=task_id,
            status="REVOKED",
            message=message
        )
        
    except Exception as e:
        logger.error(f"Failed to cancel job {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")


@router.get("/queues/status", response_model=QueuesResponse)
async def get_queue_status():
    """
    Get queue depths and worker status.
    
    Returns information about all registered queues and connected workers.
    """
    try:
        inspect = celery_app.control.inspect()
        
        # Get worker stats
        stats = inspect.stats() or {}
        active = inspect.active() or {}
        
        workers = []
        total_active = 0
        
        for hostname, worker_stats in stats.items():
            active_tasks = len(active.get(hostname, []))
            total_active += active_tasks
            
            workers.append(WorkerInfo(
                hostname=hostname,
                status="online",
                active_tasks=active_tasks,
                processed_total=worker_stats.get("total", {}).get("src.workers.tasks.process_document", 0),
                concurrency=worker_stats.get("pool", {}).get("max-concurrency", 0),
                queues=[q.get("name", "unknown") for q in worker_stats.get("queues", [])],
            ))
        
        # Get queue info (from Redis)
        queues = []
        try:
            import redis
            import os
            redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
            r = redis.from_url(redis_url)
            
            for queue_name in ["celery", "ingestion", "extraction"]:
                try:
                    count = r.llen(queue_name)
                    queues.append(QueueInfo(
                        queue_name=queue_name,
                        message_count=count,
                        consumer_count=len([w for w in workers if queue_name in w.queues]),
                    ))
                except Exception:
                    pass
        except ImportError:
            logger.warning("Redis not available for queue inspection")
        
        return QueuesResponse(
            queues=queues,
            workers=workers,
            total_active_tasks=total_active,
        )
        
    except Exception as e:
        logger.error(f"Failed to get queue status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get queue status: {str(e)}")


# =============================================================================
# Helpers
# =============================================================================

def _task_to_job_info(task: dict, default_status: str) -> JobInfo:
    """Convert Celery task dict to JobInfo."""
    task_id = task.get("id", "unknown")
    task_name = task.get("name", "unknown")
    
    # Extract progress from kwargs or args if available
    kwargs = task.get("kwargs", {})
    
    return JobInfo(
        task_id=task_id,
        task_name=task_name,
        status=default_status,
        progress=None,
        progress_message=None,
        started_at=None,
        retries=task.get("retries", 0),
    )


def _matches_filters(job: JobInfo, status: Optional[JobStatus], task_type: Optional[str]) -> bool:
    """Check if job matches filter criteria."""
    if status and job.status != status.value:
        return False
    if task_type and task_type not in (job.task_name or ""):
        return False
    return True
