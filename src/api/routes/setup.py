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


@router.get("/install/events")
async def install_events_stream(feature_ids: str):
    """
    SSE endpoint for streaming installation progress.
    
    Args:
        feature_ids: Comma-separated list of feature IDs to install.
    
    Returns:
        EventSourceResponse streaming progress events.
    """
    import json
    from sse_starlette.sse import EventSourceResponse
    
    # Parse feature IDs
    ids = [fid.strip() for fid in feature_ids.split(",") if fid.strip()]
    
    if not ids:
        raise HTTPException(status_code=400, detail="No feature IDs provided")
    
    async def event_generator():
        """Generate SSE events from installation progress."""
        service = get_setup_service()
        
        try:
            async for progress in service.install_features_stream(ids):
                yield {
                    "event": "progress",
                    "data": json.dumps(progress)
                }
            
            # Send completion event
            yield {
                "event": "complete",
                "data": json.dumps({"status": "finished"})
            }
        except Exception as e:
            logger.error(f"Installation stream error: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }
    
    return EventSourceResponse(event_generator())
