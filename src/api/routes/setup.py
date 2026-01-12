"""
Setup API
=========

Endpoints for managing optional feature installation and setup status.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import verify_admin
from src.api.services.setup_service import get_setup_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/setup",
    tags=["admin-setup"],
    dependencies=[Depends(verify_admin)]
)


class SetupStatusResponse(BaseModel):
    """Setup status response."""
    initialized: bool
    setup_complete: bool
    features: list[dict[str, Any]]
    summary: dict[str, int]


class BatchInstallRequest(BaseModel):
    """Request to install multiple features."""
    feature_ids: list[str]


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status():
    """Get current setup status and installed features."""
    try:
        service = get_setup_service()
        return service.get_setup_status()
    except Exception as e:
        logger.error(f"Failed to get setup status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/install", response_model=dict[str, Any])
async def install_features(request: BatchInstallRequest):
    """Install optional features."""
    try:
        service = get_setup_service()
        # Returns dict of results per feature
        return await service.install_features_batch(request.feature_ids)
    except Exception as e:
        logger.error(f"Failed to install features: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skip")
async def skip_setup():
    """Mark the setup wizard as complete."""
    try:
        service = get_setup_service()
        service.mark_setup_complete()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to mark setup complete: {e}")
        raise HTTPException(status_code=500, detail=str(e))
