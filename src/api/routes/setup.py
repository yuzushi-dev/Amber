"""
Setup API Routes
=================

Endpoints for managing optional dependency installation.
"""

import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel

from src.api.services.setup_service import get_setup_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])


# =============================================================================
# Request/Response Models
# =============================================================================


class FeatureStatus(BaseModel):
    """Status of an optional feature."""
    id: str
    name: str
    description: str
    size_mb: int
    status: str
    error_message: str | None = None


class SetupSummary(BaseModel):
    """Summary of feature installation status."""
    total: int
    installed: int
    installing: int
    not_installed: int


class SetupStatusResponse(BaseModel):
    """Response for setup status endpoint."""
    initialized: bool
    setup_complete: bool
    features: List[FeatureStatus]
    summary: SetupSummary


class InstallRequest(BaseModel):
    """Request to install features."""
    feature_ids: List[str]


class InstallResponse(BaseModel):
    """Response from install request."""
    success: bool
    message: str
    results: dict | None = None


class ServiceStatus(BaseModel):
    """Status of a required service."""
    status: str
    message: str


class RequiredServicesResponse(BaseModel):
    """Response for required services check."""
    all_available: bool
    services: dict[str, ServiceStatus]


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/status",
    response_model=SetupStatusResponse,
    summary="Get Setup Status",
    description="Returns the current setup status including which features are installed.",
)
async def get_setup_status() -> SetupStatusResponse:
    """Get current setup status."""
    service = get_setup_service()
    status_data = service.get_setup_status()
    
    return SetupStatusResponse(
        initialized=status_data["initialized"],
        setup_complete=status_data["setup_complete"],
        features=[FeatureStatus(**f) for f in status_data["features"]],
        summary=SetupSummary(**status_data["summary"]),
    )


@router.post(
    "/install",
    response_model=InstallResponse,
    summary="Install Features",
    description="Install one or more optional features in the background.",
)
async def install_features(
    request: InstallRequest,
    background_tasks: BackgroundTasks,
) -> InstallResponse:
    """
    Start installation of selected features.
    
    Installation runs in background. Poll /status to track progress.
    """
    service = get_setup_service()
    
    if not request.feature_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No features specified",
        )
    
    # Validate feature IDs
    valid_ids = set(service._features.keys())
    invalid_ids = [fid for fid in request.feature_ids if fid not in valid_ids]
    if invalid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown feature IDs: {invalid_ids}",
        )
    
    # Start installation in background
    async def do_install():
        await service.install_features_batch(request.feature_ids)
    
    background_tasks.add_task(do_install)
    
    return InstallResponse(
        success=True,
        message=f"Started installation of {len(request.feature_ids)} feature(s). Poll /status to track progress.",
    )


@router.post(
    "/skip",
    response_model=InstallResponse,
    summary="Skip Setup",
    description="Mark setup as complete without installing optional features.",
)
async def skip_setup() -> InstallResponse:
    """Skip optional feature installation."""
    service = get_setup_service()
    service.mark_setup_complete()
    
    return InstallResponse(
        success=True,
        message="Setup skipped. You can install optional features later from Settings.",
    )


@router.get(
    "/check-required",
    response_model=RequiredServicesResponse,
    summary="Check Required Services",
    description="Verify that required services (PostgreSQL, Neo4j, Milvus, Redis) are reachable.",
)
async def check_required_services() -> RequiredServicesResponse:
    """Check if required database drivers are available."""
    service = get_setup_service()
    result = await service.check_required_services()
    
    return RequiredServicesResponse(
        all_available=result["all_available"],
        services={k: ServiceStatus(**v) for k, v in result["services"].items()},
    )
