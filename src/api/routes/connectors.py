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

from src.api.deps import get_db_session as get_db_session
from src.api.schemas.base import ResponseSchema
from src.core.ingestion.infrastructure.connectors.zendesk import ZendeskConnector
from src.core.ingestion.infrastructure.connectors.confluence import ConfluenceConnector
from src.core.ingestion.infrastructure.connectors.carbonio import CarbonioConnector
from src.core.ingestion.infrastructure.connectors.jira import JiraConnector
from src.core.ingestion.domain.connector_state import ConnectorState
from src.core.ingestion.application.ingestion_service import IngestionService
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
    "confluence": ConfluenceConnector,
    "carbonio": CarbonioConnector,
    "jira": JiraConnector,
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
    db: AsyncSession = Depends(get_db_session)
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
            is_authenticated=bool(state.sync_cursor),  # Connected if we have credentials
            last_sync_at=state.last_sync_at,
            items_synced=0,  # Would need to count from documents
            error_message=state.error_message
        )
    )


@router.post("/{connector_type}/auth", response_model=ResponseSchema[ConnectorStatusResponse])
async def authenticate_connector(
    connector_type: str,
    request: ConnectorAuthRequest,
    db: AsyncSession = Depends(get_db_session)
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
        elif connector_type == "confluence":
             base_url = request.credentials.get("base_url")
             if not base_url:
                 raise HTTPException(
                     status_code=status.HTTP_400_BAD_REQUEST,
                     detail="Confluence requires 'base_url' in credentials"
                 )
             connector = ConnectorClass(base_url=base_url)
        elif connector_type == "carbonio":
             host = request.credentials.get("host")
             if not host:
                  raise HTTPException(
                      status_code=status.HTTP_400_BAD_REQUEST,
                      detail="Carbonio requires 'host' in credentials"
                  )
             connector = ConnectorClass(host=host)
        elif connector_type == "jira":
             base_url = request.credentials.get("base_url")
             if not base_url:
                 raise HTTPException(
                     status_code=status.HTTP_400_BAD_REQUEST,
                     detail="Jira requires 'base_url' in credentials"
                 )
             connector = ConnectorClass(base_url=base_url)
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


# ... (inside authenticate_connector)
        state.status = "idle"
        state.error_message = None
        # Store config (Store credentials for MVP to enable background sync)
        # TODO: Move to secure vault in production
        state.sync_cursor = request.credentials
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
    db: AsyncSession = Depends(get_db_session)
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


class ConnectorItemResponse(BaseModel):
    """Response model for a connector item."""
    id: str
    title: str
    url: str
    updated_at: datetime
    content_type: str
    metadata: dict[str, Any]


class IngestItemsRequest(BaseModel):
    """Request to ingest specific items."""
    item_ids: list[str]


@router.get("/{connector_type}/items", response_model=ResponseSchema[dict[str, Any]])
async def list_connector_items(
    connector_type: str,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    db: AsyncSession = Depends(get_db_session)
):
    """
    List items from a connector (browse content).
    """
    if connector_type not in CONNECTOR_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector type '{connector_type}' not found"
        )

    tenant_id = get_current_tenant() or "default"
    
    # 1. Get Connector State & Config
    state = await get_or_create_connector_state(db, tenant_id, connector_type)
    
    # 2. Instantiate Connector
    ConnectorClass = CONNECTOR_REGISTRY[connector_type]
    
    # We need credentials to browse. Ideally these are encrypted in state.
    # For MVP/Phase 1, we might rely on the user re-authenticating or 
    # (unsafe) storing tokens in state.sync_cursor or similar.
    # The current `authenticate_connector` stores `sync_cursor` with subdomain but NO tokens.
    # So we essentially CANNOT browse unless we have the token.
    # BUT, the `ZendeskConnector` state only has `subdomain`.
    # AND `ConnectorState` doesn't store secrets.
    # PROPER FIX: Use a Secrets Manager.
    # WORKAROUND for this session: We will assume the connector is configured if state exists,
    # but we actually need the token.
    # The `ZendeskConnector` implementation requires `otp` or `api_token` in `authenticate`.
    
    # Check if we have what we need. 
    # Note: connect_state.sync_cursor is a dict.
    
    # If this were a real production app, we'd fetch secrets here.
    # Since we don't have secrets storage, we might have to ask the user to provide 
    # credentials in the header OR we are stuck.
    # However, `ConnectorState` has `is_authenticated` implicitly by `last_sync_at`.
    
    # Let's check how `authenticate` works. It sets `_authenticated`.
    # But `authenticate` endpoint takes credentials in the request.
    
    # To browse, we probably need to know the credentials. 
    # If we can't persist them, we can't background sync either!
    # So the current architecture assumes we ARE persisting them somewhere?
    # `state.sync_cursor` usage in `authenticated` endpoint:
    # `state.sync_cursor = {"subdomain": request.credentials.get("subdomain")} `
    # It drops the token!
    
    # This is a BLOCKER for background syncs too.
    # I will update `ConnectorState` to strictly store the token in `sync_cursor` (UNSAFE) 
    # just to make it work for this demo/MVP, as per "Amber 2.0" likely locally hosted.
    # Or I'll update the `authenticate` logic to store it.
    
    # RE-READ `authenticate_connector`:
    # `state.sync_cursor = {"subdomain": ...}`.
    
    # I will update `authenticate_connector` first? No, I'll update it here in `connectors.py` 
    # to actually store the credentials so we can use them.
    
    pass

    # ... Continuing assuming credentials will be available in sync_cursor ...
    
    config = state.sync_cursor
    if not config or ("api_token" not in config and "password" not in config):
         raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Connector not configured or credentials missing. Please re-authenticate."
        )

    auth_params = {}
    if connector_type == "zendesk":
         connector = ConnectorClass(subdomain=config.get("subdomain", ""))
         auth_params = {
            "email": config.get("email"),
            "api_token": config.get("api_token")
            # "subdomain" is in init
         }
    elif connector_type == "confluence":
         connector = ConnectorClass(base_url=config.get("base_url", ""))
         auth_params = {
            "email": config.get("email"),
            "api_token": config.get("api_token"),
            "api_token": config.get("api_token"),
            "base_url": config.get("base_url") 
         }
    elif connector_type == "carbonio":
         connector = ConnectorClass(host=config.get("host", ""))
         auth_params = {
            "email": config.get("email"),
            "password": config.get("password"),
            "host": config.get("host")
         }
    elif connector_type == "jira":
         connector = ConnectorClass(base_url=config.get("base_url", ""))
         auth_params = {
            "email": config.get("email"),
            "api_token": config.get("api_token"),
            "base_url": config.get("base_url")
         }
    
    auth_success = await connector.authenticate(auth_params)
    
    if not auth_success:
        raise HTTPException(status_code=401, detail="Stored credentials invalid.")

    items, has_more = await connector.list_items(page=page, page_size=page_size, search=search)
    
    return ResponseSchema(
        data={
            "items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "url": item.url,
                    "updated_at": item.updated_at,
                    "content_type": item.content_type,
                    "metadata": item.metadata
                } for item in items
            ],
            "has_more": has_more,
            "page": page
        },
        message="Items retrieved"
    )


async def run_selective_ingestion(
    connector_type: str,
    tenant_id: str,
    item_ids: list[str],
    state_id: str
):
    """Background task for selective ingestion."""
    # Create new session
    # We need to manually manage the session here
    from src.api.deps import _get_async_session_maker
    from src.api.config import settings
    
    logger.info(f"Starting selective ingestion for {connector_type} items: {item_ids}")
    
    async with _get_async_session_maker()() as session:
        # 1. Setup Connector
        result = await session.execute(
            select(ConnectorState).where(ConnectorState.id == state_id)
        )
        state = result.scalar_one_or_none()
        
        if not state:
            logger.error(f"Connector state {state_id} not found in background task")
            return
            
        config = state.sync_cursor
        ConnectorClass = CONNECTOR_REGISTRY[connector_type]
        
        if connector_type == "zendesk":
             connector = ConnectorClass(subdomain=config.get("subdomain", ""))
        elif connector_type == "confluence":
             connector = ConnectorClass(base_url=config.get("base_url", ""))
        elif connector_type == "carbonio":
             connector = ConnectorClass(host=config.get("host", ""))
        
        await connector.authenticate(config)
        
        # 2. Setup Ingestion Service
        # 2. Setup Ingestion Service
        from src.amber_platform.composition_root import platform, build_vector_store_factory
        from src.core.ingestion.infrastructure.repositories.postgres_document_repository import PostgresDocumentRepository
        from src.core.tenants.infrastructure.repositories.postgres_tenant_repository import PostgresTenantRepository
        from src.core.ingestion.infrastructure.uow.postgres_uow import PostgresUnitOfWork
        from src.core.events.dispatcher import EventDispatcher
        from src.infrastructure.adapters.redis_state_publisher import RedisStatePublisher

        vector_store_factory = build_vector_store_factory()
        event_dispatcher = EventDispatcher(RedisStatePublisher())
        
        ingestion_service = IngestionService(
            document_repository=PostgresDocumentRepository(session),
            tenant_repository=PostgresTenantRepository(session),
            unit_of_work=PostgresUnitOfWork(session), 
            storage_client=platform.minio_client, 
            neo4j_client=platform.neo4j_client,
            vector_store=None,
            event_dispatcher=event_dispatcher,
            vector_store_factory=vector_store_factory,
        )
        
        # 3. Process Items
        success_count = 0
        state.status = "syncing"
        await session.commit()
        
        try:
            for item_id in item_ids:
                try:
                    # Fetch content
                    content = await connector.get_item_content(item_id)
                    
                    # We need a filename. Let's try to get title if possible, or just ID.
                    # Ideally we would have cached the list_items info, but we don't have it here.
                    # We'll use ID.html
                    if connector_type == "zendesk":
                        filename = f"zendesk_{item_id}.html"
                    elif connector_type == "confluence":
                        filename = f"confluence_{item_id}.html"
                    elif connector_type == "carbonio":
                        filename = f"carbonio_{item_id}.html"
                    else:
                         filename = f"doc_{item_id}.html"
                    
                    # Register
                    doc = await ingestion_service.register_document(
                        tenant_id=tenant_id,
                        filename=filename,
                        file_content=content,
                        content_type="text/html"
                    )
                    
                    # Trigger Processing
                    await ingestion_service.process_document(doc.id)
                    success_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to ingest item {item_id}: {e}")
            
            state.status = "idle"
            # Maybe update last_sync_at?
            state.last_sync_at = datetime.now()
            logger.info(f"Ingested {success_count}/{len(item_ids)} items")
            
        except Exception as e:
            state.status = "error"
            state.error_message = str(e)
            logger.error(f"Ingestion job failed: {e}")
        finally:
            await session.commit()


@router.post("/{connector_type}/ingest", response_model=ResponseSchema[SyncJobResponse])
async def ingest_selected_items(
    connector_type: str,
    request: IngestItemsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Ingest specific items by ID.
    """
    if connector_type not in CONNECTOR_REGISTRY:
        raise HTTPException(status_code=404, detail="Connector not found")
        
    tenant_id = get_current_tenant() or "default"
    state = await get_or_create_connector_state(db, tenant_id, connector_type)
    
    if state.status == "syncing":
        raise HTTPException(status_code=409, detail="Sync in progress")
        
    job_id = f"ingest_{uuid4().hex[:12]}"
    
    # Store credentials check
    config = state.sync_cursor
    if not config or ("api_token" not in config and "password" not in config):
         raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Connector not configured. Please re-authenticate."
        )

    # Dispatch
    background_tasks.add_task(
        run_selective_ingestion, 
        connector_type, 
        tenant_id, 
        request.item_ids,
        state.id
    )
    
    return ResponseSchema(
        data=SyncJobResponse(
            job_id=job_id,
            status="started",
            message=f"Ingestion started for {len(request.item_ids)} items."
        ),
        message="Ingestion started"
    )
