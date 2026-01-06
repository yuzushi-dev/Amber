"""
Connector API Routes
====================

Endpoints for managing external data source connectors.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.api.schemas.base import ResponseSchema
from src.core.connectors.zendesk import ZendeskConnector
from src.core.models.connector_state import ConnectorState
from src.shared.context import get_current_tenant

router = APIRouter(prefix="/connectors", tags=["connectors"])
logger = logging.getLogger(__name__)


# --- Request/Response Models ---

class ConnectorAuthRequest(BaseModel):
    """Authentication credentials for a connector."""
    credentials: dict[str, Any]


class ConnectorSyncRequest(BaseModel):
    """Options for triggering a sync."""
    full_sync: bool = False  # If True, ignore last_sync_at


class ConnectorStatusResponse(BaseModel):
    """Status of a connector."""
    connector_type: str
    status: str
    is_authenticated: bool
    last_sync_at: datetime | None = None
    items_synced: int = 0
    error_message: str | None = None


class SyncJobResponse(BaseModel):
    """Response when a sync job is started."""
    job_id: str
    status: str
    message: str


# --- Connector Registry ---

CONNECTOR_REGISTRY = {
    "zendesk": ZendeskConnector,
    # Add more connectors here as they are implemented
    # "confluence": ConfluenceConnector,
}


async def get_or_create_connector_state(
    db: AsyncSession,
    tenant_id: str,
    connector_type: str
) -> ConnectorState:
    """Get existing connector state or create a new one."""
    result = await db.execute(
        select(ConnectorState).where(
            ConnectorState.tenant_id == tenant_id,
            ConnectorState.connector_type == connector_type
        )
    )
    state = result.scalar_one_or_none()

    if not state:
        state = ConnectorState(
            id=f"conn_{uuid4().hex[:16]}",
            tenant_id=tenant_id,
            connector_type=connector_type,
            status="idle"
        )
        db.add(state)
        await db.commit()
        await db.refresh(state)

    return state


# --- Endpoints ---

@router.get("/", response_model=ResponseSchema[list[str]])
async def list_available_connectors():
    """List all available connector types."""
    return ResponseSchema(
        data=list(CONNECTOR_REGISTRY.keys()),
        message="Available connectors"
    )


@router.get("/{connector_type}/status", response_model=ResponseSchema[ConnectorStatusResponse])
async def get_connector_status(
    connector_type: str,
    db: AsyncSession = Depends(get_db)
):
    """Get the status of a specific connector."""
    if connector_type not in CONNECTOR_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector type '{connector_type}' not found"
        )

    tenant_id = get_current_tenant() or "default"
    state = await get_or_create_connector_state(db, tenant_id, connector_type)

    return ResponseSchema(
        data=ConnectorStatusResponse(
            connector_type=state.connector_type,
            status=state.status,
            is_authenticated=state.last_sync_at is not None,  # Approximation
            last_sync_at=state.last_sync_at,
            items_synced=0,  # Would need to count from documents
            error_message=state.error_message
        )
    )


@router.post("/{connector_type}/auth", response_model=ResponseSchema[ConnectorStatusResponse])
async def authenticate_connector(
    connector_type: str,
    request: ConnectorAuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate a connector with external service.

    Credentials vary by connector type:
    - zendesk: {subdomain, email, api_token}
    - confluence: {base_url, email, api_token}
    """
    if connector_type not in CONNECTOR_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector type '{connector_type}' not found"
        )

    tenant_id = get_current_tenant() or "default"

    # Get connector class and instantiate
    ConnectorClass = CONNECTOR_REGISTRY[connector_type]

    try:
        if connector_type == "zendesk":
            subdomain = request.credentials.get("subdomain")
            if not subdomain:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Zendesk requires 'subdomain' in credentials"
                )
            connector = ConnectorClass(subdomain=subdomain)
        else:
            connector = ConnectorClass()

        # Attempt authentication
        success = await connector.authenticate(request.credentials)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed. Check credentials."
            )

        # Update state
        state = await get_or_create_connector_state(db, tenant_id, connector_type)
        state.status = "idle"
        state.error_message = None
        # Store config (but NOT credentials - those should be in a secure vault)
        state.sync_cursor = {"subdomain": request.credentials.get("subdomain")} if connector_type == "zendesk" else {}
        await db.commit()
        await db.refresh(state)

        logger.info(f"Connector {connector_type} authenticated for tenant {tenant_id}")

        return ResponseSchema(
            data=ConnectorStatusResponse(
                connector_type=state.connector_type,
                status=state.status,
                is_authenticated=True,
                last_sync_at=state.last_sync_at,
                items_synced=0,
                error_message=None
            ),
            message="Authentication successful"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Connector authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication error: {str(e)}"
        ) from e


@router.post("/{connector_type}/sync", response_model=ResponseSchema[SyncJobResponse])
async def trigger_sync(
    connector_type: str,
    request: ConnectorSyncRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger a sync operation for a connector.

    Returns immediately with a job ID. Use GET /status to check progress.
    """
    if connector_type not in CONNECTOR_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector type '{connector_type}' not found"
        )

    tenant_id = get_current_tenant() or "default"
    state = await get_or_create_connector_state(db, tenant_id, connector_type)

    if state.status == "syncing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync already in progress"
        )

    # Update state to syncing
    state.status = "syncing"
    state.error_message = None
    await db.commit()

    job_id = f"sync_{uuid4().hex[:12]}"

    # TODO: In production, this would dispatch a Celery task
    # For now, we just return the job ID
    # background_tasks.add_task(run_sync, connector_type, tenant_id, job_id, request.full_sync)

    logger.info(f"Sync triggered for {connector_type} tenant {tenant_id}, job {job_id}")

    return ResponseSchema(
        data=SyncJobResponse(
            job_id=job_id,
            status="started",
            message=f"Sync job started. Use GET /connectors/{connector_type}/status to check progress."
        ),
        message="Sync started"
    )
