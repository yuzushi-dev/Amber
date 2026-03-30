"""
Provisioning Routes
===================

Admin endpoints to provision a tenant with documents (and optionally
the knowledge graph) from another tenant without re-ingesting files.

Flow:
  1. POST /v1/admin/provisioning/tenants/{target_tenant_id}  → 202 + job_id
  2. GET  /v1/admin/provisioning/jobs/{job_id}               → poll status
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import verify_admin, verify_super_admin
from src.api.deps import get_db_session
from src.core.admin_ops.application.provisioning_policy import (
    ProvisioningDisabledError,
    ensure_tenant_provisioning_enabled,
)
from src.core.admin_ops.domain.provisioning_job import ProvisioningJob, ProvisioningStatus
from src.core.tenants.application.tenant_service import TenantService

router = APIRouter(prefix="/provisioning", tags=["admin-provisioning"])
logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────── #


class ProvisionRequest(BaseModel):
    """Body for starting a provisioning job."""

    source_tenant_id: str
    document_ids: list[str] | None = None   # null = all READY docs
    folder_ids: list[str] | None = None     # alternative: filter by folder
    include_graph: bool = False


class ProvisionResponse(BaseModel):
    job_id: str
    status: str
    message: str


class ProvisionJobResponse(BaseModel):
    id: str
    target_tenant_id: str
    source_tenant_id: str
    status: str
    progress: int
    docs_copied: int
    chunks_copied: int
    vectors_copied: int
    graph_nodes_copied: int
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


def _job_to_response(job: ProvisioningJob) -> ProvisionJobResponse:
    return ProvisionJobResponse(
        id=job.id,
        target_tenant_id=job.target_tenant_id,
        source_tenant_id=job.source_tenant_id,
        status=job.status.value if isinstance(job.status, ProvisioningStatus) else job.status,
        progress=job.progress,
        docs_copied=job.docs_copied,
        chunks_copied=job.chunks_copied,
        vectors_copied=job.vectors_copied,
        graph_nodes_copied=job.graph_nodes_copied,
        error_message=job.error_message,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


# ── Endpoints ──────────────────────────────────────────────────────────── #


@router.post(
    "/tenants/{target_tenant_id}",
    response_model=ProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_super_admin)],
    summary="Provision a tenant with documents from another tenant",
)
async def start_provisioning(
    target_tenant_id: str,
    request: ProvisionRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProvisionResponse:
    """
    Start a background job that copies documents, chunks and vectors from
    *source_tenant_id* into *target_tenant_id*.  Returns immediately with a
    **job_id** to poll for progress.

    - `document_ids` – copy only these documents (null = all READY docs)
    - `folder_ids`   – alternative filter; ignored if `document_ids` is set
    - `include_graph` – also copy the Entity knowledge graph (default false)
    """
    try:
        ensure_tenant_provisioning_enabled()
    except ProvisioningDisabledError as e:
        logger.warning(
            "Blocked legacy tenant provisioning %s -> %s by policy: %s",
            request.source_tenant_id,
            target_tenant_id,
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    from src.workers.provisioning_tasks import provision_tenant

    if request.source_tenant_id == target_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_tenant_id and target_tenant_id must differ",
        )

    svc = TenantService(session)
    if not await svc.get_tenant(request.source_tenant_id):
        raise HTTPException(status_code=404, detail="Source tenant not found")
    if not await svc.get_tenant(target_tenant_id):
        raise HTTPException(status_code=404, detail="Target tenant not found")

    # Guard: refuse if a job is already running for this target
    active = await session.execute(
        select(ProvisioningJob)
        .where(ProvisioningJob.target_tenant_id == target_tenant_id)
        .where(ProvisioningJob.status.in_(["pending", "running"]))
    )
    if active.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A provisioning job is already running for this tenant",
        )

    job = ProvisioningJob(
        id=str(uuid4()),
        target_tenant_id=target_tenant_id,
        source_tenant_id=request.source_tenant_id,
        document_ids=request.document_ids,
        folder_ids=request.folder_ids,
        include_graph=request.include_graph,
        status=ProvisioningStatus.PENDING,
    )
    session.add(job)
    await session.commit()

    provision_tenant.delay(job.id)

    return ProvisionResponse(
        job_id=job.id,
        status="pending",
        message=f"Provisioning started: {request.source_tenant_id} → {target_tenant_id}",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ProvisionJobResponse,
    dependencies=[Depends(verify_admin)],
    summary="Get provisioning job status",
)
async def get_provisioning_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ProvisionJobResponse:
    result = await session.execute(
        select(ProvisioningJob).where(ProvisioningJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Provisioning job not found")
    return _job_to_response(job)


@router.get(
    "/tenants/{target_tenant_id}/jobs",
    response_model=list[ProvisionJobResponse],
    dependencies=[Depends(verify_admin)],
    summary="List provisioning jobs for a tenant",
)
async def list_provisioning_jobs(
    target_tenant_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProvisionJobResponse]:
    result = await session.execute(
        select(ProvisioningJob)
        .where(ProvisioningJob.target_tenant_id == target_tenant_id)
        .order_by(ProvisioningJob.created_at.desc())
    )
    return [_job_to_response(j) for j in result.scalars().all()]


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_super_admin)],
    summary="Cancel a pending provisioning job",
)
async def cancel_provisioning_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    result = await session.execute(
        select(ProvisioningJob).where(ProvisioningJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Provisioning job not found")
    if job.status != ProvisioningStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a job in '{job.status}' state (only PENDING jobs can be cancelled)",
        )
    job.status = ProvisioningStatus.FAILED
    job.error_message = "Cancelled by admin"
    await session.commit()
