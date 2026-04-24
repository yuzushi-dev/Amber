"""
Document API Routes
===================

Endpoints for document management.
Phase 1: Full implementation with async processing.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from src.amber_platform.composition_root import build_vector_store_factory, platform
from src.api.config import settings
from src.api.deps import get_db_session as get_db_session
from src.core.ingestion.domain.document import Document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_content_type(document: Document) -> str | None:
    """
    Get content type for a document.

    Checks metadata first, then derives from filename extension.
    """
    # Check if content_type is stored in metadata
    if document.metadata_ and isinstance(document.metadata_, dict):
        content_type = document.metadata_.get("content_type")
        if content_type:
            return content_type

    # Derive from filename extension
    filename = document.filename.lower()
    if filename.endswith(".pdf"):
        return "application/pdf"
    elif filename.endswith((".md", ".markdown")):
        return "text/markdown"
    elif filename.endswith(".txt"):
        return "text/plain"
    elif filename.endswith(".html"):
        return "text/html"
    elif filename.endswith(".json"):
        return "application/json"
    elif filename.endswith(".csv"):
        return "text/csv"
    else:
        return "text/plain"  # Default fallback


def _get_tenant_id(request: Request) -> str:
    """Resolve tenant ID from request context. Raises 401 if not authenticated."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: tenant context missing.",
        )
    return str(tenant_id)


async def _record_document_visibility_counter(counter_name: str, tenant_id: str) -> None:
    """Best-effort operational counter for document visibility checks."""
    from src.amber_platform.composition_root import build_metrics_collector

    collector = build_metrics_collector()
    increment = getattr(collector, "increment_counter", None)
    if not callable(increment):
        return

    try:
        await increment(counter_name, tenant_id, 1)
    except Exception as e:
        logger.warning(
            f"Failed to record document visibility metric {counter_name} for tenant {tenant_id}: {e}"
        )


async def _record_document_visibility_miss(
    document_id: str,
    http_request: Request | None,
    session: AsyncSession,
) -> None:
    """Classify a 404 on document visibility as denied vs not found."""
    if http_request is None:
        return

    permissions = getattr(http_request.state, "permissions", [])
    if "super_admin" in permissions:
        return

    from src.core.ingestion.domain.document_share import DocumentVisibilityStatus
    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )
    from src.core.tenants.application.query_scopes import resolve_query_scopes

    tenant_id = _get_tenant_id(http_request)
    repository = PostgresDocumentRepository(session)
    visibility_status = DocumentVisibilityStatus.NOT_FOUND
    classifier = getattr(repository, "classify_visibility", None)
    if callable(classifier):
        query_scopes = getattr(http_request.state, "query_scopes", None)
        if query_scopes is None:
            query_scopes = resolve_query_scopes(tenant_id)

        shared_owner_tenant_ids = list(
            getattr(query_scopes, "shared_document_owner_tenants", []) or []
        )
        visibility_status = await classifier(
            document_id=document_id,
            viewer_tenant_id=tenant_id,
            shared_owner_tenant_ids=shared_owner_tenant_ids,
        )

    counter_name = "document_visibility_denied"
    if visibility_status != DocumentVisibilityStatus.DENIED:
        counter_name = "document_visibility_not_found"

    await _record_document_visibility_counter(counter_name, tenant_id)


async def _get_visible_document_or_404(
    document_id: str,
    http_request: Request | None,
    session: AsyncSession,
):
    """Resolve a document visible to the current tenant or raise 404."""
    if http_request is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Request context missing.",
        )

    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    if is_super_admin:
        from src.core.ingestion.domain.document_share import VisibleDocument

        result = await session.execute(
            select(Document)
            .options(selectinload(Document.folder))
            .where(Document.id == document_id)
        )
        document = result.scalars().first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found",
            )

        return VisibleDocument(
            document=document,
            is_shared=False,
            owner_tenant_id=document.tenant_id,
            visible_from_tenant_id=document.tenant_id,
            share_mode=None,
        )

    from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )

    tenant_id = _get_tenant_id(http_request)
    repository = PostgresDocumentRepository(session)
    visible_document = await repository.get_visible(document_id, tenant_id)
    if not visible_document:
        await _record_document_visibility_miss(document_id, http_request, session)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )
    return visible_document


def _require_document_share_manager(request: Request) -> str:
    """Allow share management only for super admins or default tenant admins."""
    permissions = getattr(request.state, "permissions", [])
    if "super_admin" in permissions:
        return str(getattr(request.state, "api_key_name", "super_admin"))

    tenant_id = _get_tenant_id(request)
    tenant_role = getattr(request.state, "tenant_role", None)
    if tenant_id != "default" or tenant_role != "admin" or "admin" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Default tenant admin privileges required.",
        )

    return str(getattr(request.state, "api_key_name", "default_admin"))


def _parse_shared_with_tenant_ids(raw_value: str | None) -> list[str] | None:
    """Parse optional multipart JSON array of tenant IDs."""
    if raw_value is None:
        return None

    candidate = raw_value.strip()
    if not candidate:
        return []

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shared_with_tenant_ids must be a JSON array of tenant IDs.",
        ) from e

    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shared_with_tenant_ids must be a JSON array of tenant IDs.",
        )

    return parsed


def _ensure_document_share_management_enabled() -> None:
    """Reject explicit share-management routes when the feature is disabled."""
    if not settings.enable_document_share_management:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document share management is disabled on this server.",
        )


def _ensure_upload_time_document_shares_enabled() -> None:
    """Reject upload-time share target selection when the feature is disabled."""
    if not settings.enable_upload_time_document_shares:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload-time document sharing is disabled on this server.",
        )


class DocumentUploadResponse(BaseModel):
    """Response model for document upload."""

    document_id: str
    status: str
    events_url: str
    message: str


class DocumentResponse(BaseModel):
    """Response model for document details."""

    id: str
    filename: str
    title: str  # Alias for filename (for frontend compatibility)
    status: str
    domain: str | None = None
    tenant_id: str
    folder_id: str | None = None
    source_type: str | None = "upload"
    content_type: str | None = None  # MIME type of the document
    created_at: datetime
    error_message: str | None = None  # Added field for error feedback
    is_shared: bool = False
    owner_tenant_id: str | None = None
    visible_from_tenant_id: str | None = None
    share_mode: str | None = None

    # Enrichment fields
    summary: str | None = None
    document_type: str | None = None
    keywords: list[str] = []
    hashtags: list[str] = []
    metadata: dict[str, Any] | None = None

    # Stats (computed from chunks/entities/relationships)
    stats: dict[str, int] | None = None
    ingestion_cost: float | None = 0.0



class DocumentShareRequest(BaseModel):
    """Request model for adding, replacing, or removing share targets."""

    tenant_ids: list[str] = Field(default_factory=list)


class DocumentShareTargetResponse(BaseModel):
    """Response model for one shared tenant target."""

    tenant_id: str
    tenant_name: str | None = None
    share_mode: str
    created_at: datetime


class DocumentSharesResponse(BaseModel):
    """Response model for document share configuration."""

    document_id: str
    owner_tenant_id: str
    shares: list[DocumentShareTargetResponse] = Field(default_factory=list)


def _to_document_shares_response(output) -> DocumentSharesResponse:
    return DocumentSharesResponse(
        document_id=output.document_id,
        owner_tenant_id=output.owner_tenant_id,
        shares=[
            DocumentShareTargetResponse(
                tenant_id=share.tenant_id,
                tenant_name=share.tenant_name,
                share_mode=share.share_mode,
                created_at=share.created_at,
            )
            for share in output.shares
        ],
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
    summary="Upload Document",
    description="""
    Upload a document for ingestion into the knowledge base.

    Returns 202 Accepted immediately with a document ID.
    Use the events_url to monitor processing progress via SSE.
    """,
)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="Document file to upload"),
    tenant_id: str = Form(default=None, description="Tenant ID (optional, super admin only)"),
    metadata: str = Form(default=None, description="JSON metadata (optional)"),
    folder_id: str = Form(default=None, description="Folder ID (optional)"),
    shared_with_tenant_ids: str = Form(
        default=None,
        description="JSON array of tenant IDs to share a default-owned document with immediately.",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentUploadResponse:
    """
    Upload a document for async ingestion.
    """
    from src.core.ingestion.application.use_cases_documents import UploadDocumentRequest

    # Resolve Tenant
    permissions = getattr(request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    target_tenant_id = None
    if is_super_admin and tenant_id:
        target_tenant_id = tenant_id
    else:
        target_tenant_id = _get_tenant_id(request)

    parsed_share_targets = _parse_shared_with_tenant_ids(shared_with_tenant_ids)
    share_actor = None
    if parsed_share_targets is not None:
        _ensure_upload_time_document_shares_enabled()
        if target_tenant_id != "default":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="shared_with_tenant_ids is only allowed when uploading into the default tenant.",
            )
        share_actor = _require_document_share_manager(request)

    # Parse metadata if provided
    metadata_dict = None
    if metadata:
        try:
            import json
            metadata_dict = json.loads(metadata)
        except Exception as e:
            logger.warning(f"Failed to parse metadata: {e}")

    # Read file content
    content = await file.read()

    # Build use case with dependencies
    from src.amber_platform.composition_root import build_upload_document_use_case

    max_size = settings.uploads.max_size_mb * 1024 * 1024
    use_case = build_upload_document_use_case(session=session, max_size_bytes=max_size)

    # Execute use case
    try:
        result = await use_case.execute(
            UploadDocumentRequest(
                tenant_id=target_tenant_id,
                filename=file.filename or "unnamed",
                content=content,
                content_type=file.content_type or "application/octet-stream",
                metadata=metadata_dict,
                folder_id=folder_id,
                shared_with_tenant_ids=parsed_share_targets,
                share_actor=share_actor,
            )
        )
    except ValueError as e:
        # Map domain errors to HTTP errors
        if "empty" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        elif "too large" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)
            ) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    # Build events URL
    events_url = f"/v1/documents/{result.document_id}/events"

    logger.info(f"Document {result.document_id} uploaded, processing dispatched")

    return DocumentUploadResponse(
        document_id=result.document_id,
        status=result.status,
        events_url=events_url,
        message=result.message,
    )


@router.get(
    "/{document_id}/events",
    summary="Document Processing Events",
    description="""
    Server-Sent Events (SSE) endpoint for monitoring document processing status in real-time.

    Subscribe to this endpoint to receive status updates as the document moves through
    the ingestion pipeline (extracting, classifying, chunking, embedding, graph_sync, ready).
    """,
)
async def document_events(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Stream document processing events via SSE.

    This endpoint subscribes to Redis pub/sub for real-time status updates.
    """
    visible_document = await _get_visible_document_or_404(document_id, http_request, session)
    document = visible_document.document
    tenant_id = visible_document.owner_tenant_id

    async def event_generator():
        """Generate SSE events from Redis pub/sub."""
        redis_client = None
        pubsub = None

        try:
            # Connect to Redis
            redis_client = redis.from_url(settings.db.redis_url, decode_responses=True)
            pubsub = redis_client.pubsub()

            # Subscribe to tenant-qualified status channel
            channel = f"document:{tenant_id}:{document_id}:status"
            await pubsub.subscribe(channel)

            logger.info(f"SSE client connected for document {document_id}")

            # Send initial status
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "document_id": document_id,
                        "status": document.status.value,
                        "message": f"Monitoring document {document_id}",
                    }
                ),
            }

            # Listen for Redis pub/sub messages
            while True:
                try:
                    # Use timeout to allow periodic checks
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0
                    )

                    if message and message["type"] == "message":
                        # Forward the Redis message as SSE event
                        data = message["data"]

                        # Parse and re-serialize to ensure valid JSON
                        if isinstance(data, str):
                            event_data = json.loads(data)
                        else:
                            event_data = data

                        yield {"event": "status", "data": json.dumps(event_data)}

                        # Close connection if document reached terminal state
                        if event_data.get("status") in ["ready", "failed", "completed"]:
                            logger.info(
                                f"Document {document_id} reached terminal state: {event_data.get('status')}"
                            )
                            break

                except TimeoutError:
                    # Send keepalive comment to prevent connection timeout
                    yield {"comment": "keepalive"}
                    continue

        except Exception as e:
            logger.error(f"SSE error for document {document_id}: {e}")
            yield {"event": "error", "data": json.dumps({"error": str(e)})}
        finally:
            # Cleanup
            if pubsub:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            if redis_client:
                await redis_client.close()
            logger.info(f"SSE client disconnected for document {document_id}")

    return EventSourceResponse(event_generator())


@router.get(
    "",
    summary="List Documents",
    description="List all documents in the knowledge base.",
)
async def list_documents(
    http_request: Request,
    tenant_id: str = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentResponse]:
    """
    List documents in the knowledge base.
    """
    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    def enrich_metadata(doc):
        meta = doc.metadata_ or {}
        if doc.folder:
            meta = meta.copy()
            meta["folder"] = doc.folder.name
        return meta

    if is_super_admin:
        from src.core.ingestion.domain.document_share import VisibleDocument
        from sqlalchemy import text as _text

        # Build canonical folder_id mapping: non-default folder → default folder with same name
        # This allows the frontend to filter by canonical folder_id and see all tenants' docs.
        folder_map_raw = await session.execute(
            _text(
                "SELECT non_def.id AS src_id, def.id AS canonical_id "
                "FROM folders non_def "
                "JOIN folders def ON def.name = non_def.name AND def.tenant_id = 'default' "
                "WHERE non_def.tenant_id != 'default'"
            )
        )
        folder_id_map: dict[str, str] = {r["src_id"]: r["canonical_id"] for r in folder_map_raw.mappings()}

        query = select(Document).options(selectinload(Document.folder))
        if tenant_id:
            query = query.where(Document.tenant_id == tenant_id)

        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        visible_documents = [
            VisibleDocument(
                document=doc,
                is_shared=False,
                owner_tenant_id=doc.tenant_id,
                visible_from_tenant_id=doc.tenant_id,
                share_mode=None,
            )
            for doc in result.scalars().all()
        ]
    else:
        from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
            PostgresDocumentRepository,
        )
        from sqlalchemy import text as _text

        current_tenant = _get_tenant_id(http_request)
        repository = PostgresDocumentRepository(session)
        visible_documents = await repository.list_visible_by_tenant(
            current_tenant, limit=limit, offset=offset
        )

        # Map default-tenant folder IDs to this tenant's same-name folder IDs
        # so shared documents appear in the correct local folder instead of Unfiled.
        if current_tenant != "default":
            _map_raw = await session.execute(
                _text(
                    "SELECT def.id AS src_id, local.id AS canonical_id "
                    "FROM folders def "
                    "JOIN folders local ON local.name = def.name "
                    "  AND local.tenant_id = :tenant "
                    "WHERE def.tenant_id = 'default'"
                ),
                {"tenant": current_tenant},
            )
            folder_id_map = {r["src_id"]: r["canonical_id"] for r in _map_raw.mappings()}
        else:
            folder_id_map = {}

    # folder_id_map populated for both super-admin and regular tenants with shared docs
    _folder_id_map: dict[str, str] = locals().get("folder_id_map", {})

    return [
        DocumentResponse(
            id=visible.document.id,
            filename=visible.document.filename,
            title=visible.document.filename,
            status=visible.document.status.value,
            domain=visible.document.domain,
            tenant_id=visible.document.tenant_id,
            folder_id=_folder_id_map.get(visible.document.folder_id, visible.document.folder_id),
            source_type=visible.document.source_type,
            content_type=_get_content_type(visible.document),
            created_at=visible.document.created_at,
            error_message=visible.document.error_message,
            ingestion_cost=0.0,
            metadata=enrich_metadata(visible.document),
            is_shared=visible.is_shared,
            owner_tenant_id=visible.owner_tenant_id,
            visible_from_tenant_id=visible.visible_from_tenant_id,
            share_mode=visible.share_mode,
        )
        for visible in visible_documents
    ]


@router.get(
    "/{document_id}",
    summary="Get Document",
    description="Get details of a specific document including enrichment data and stats.",
)
async def get_document(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    """
    Get document details with enrichment data and statistics.
    """
    # Need to query SQL for simple document fields first if the use case doesn't return everything
    # or ensure use case returns everything including error_message.
    # The UseCase returns DocumentOutput which maps domain model.
    # Let's check DocumentOutput definition. If it's not there, we might need to fetch from SQL directly or update UseCase.
    # For now, let's fetch directly from DB to be safe and consistent with list_documents,
    # OR we can just rely on the Use Case if we update it.
    # Actually, looking at the code below, it uses `DocumentOutput`.
    # I should check `use_cases_documents.py` to see if `DocumentOutput` has `error_message`.
    # If not, I should probably update `DocumentOutput` too.
    # But as a quick fix/pragmatic approach, I can fetch the doc from SQL for `error_message` if needed,
    # OR better: Assuming I can't easily change the UseCase file right now without finding it,
    # I will stick to what I can see.
    # However, `get_document` uses the UseCase. The UseCase likely retrieves the generic Document object.
    # Let's assume I need to update the UseCase or wrapper.
    # Wait, I don't see `use_cases_documents.py` in my file list.
    # Let's try to update the `DocumentResponse` construction below assuming `output` has it or I can mix it in.
    # But `output` is typed `DocumentOutput`.
    # Let's look at `DocumentOutput` definition if possible.
    # Since I cannot see it, and I want to avoid breaking things, I will verify `use_cases_documents.py`.

    # Actually, to save tool calls, I can see `list_documents` uses SQL directly (lines 316-332).
    # `get_document` uses `GetDocumentUseCase`.
    # If I only update `list_documents`, the list view (LiveStatusBadge) will work.
    # The detail page might not show the error if I don't update the use case.
    # But the immediate requirement is the LIST view badge/tooltip.

    # Let's update `list_documents` first (already included in first chunk).

    # Now for `get_document`:
    # It returns `DocumentResponse`.
    # I will check if I can modify `DocumentOutput` by searching for it.

    from src.core.ingestion.application.use_cases_documents import (
        DocumentOutput,
        GetDocumentRequest,
        GetDocumentUseCase,
    )

    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions
    tenant_id = None
    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)

    use_case = GetDocumentUseCase(session=session, graph_client=platform.neo4j_client)
    try:
        output: DocumentOutput = await use_case.execute(
            GetDocumentRequest(
                document_id=document_id, tenant_id=tenant_id, is_super_admin=is_super_admin
            )
        )
    except LookupError as e:
        await _record_document_visibility_miss(document_id, http_request, session)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    return DocumentResponse(
        id=output.id,
        filename=output.filename,
        title=output.title,
        status=output.status,
        domain=output.domain,
        tenant_id=output.tenant_id,
        folder_id=output.folder_id,
        source_type=output.source_type,
        content_type=output.content_type,
        created_at=output.created_at,
        summary=output.summary,
        document_type=output.document_type,
        keywords=output.keywords,
        hashtags=output.hashtags,
        metadata=output.metadata,
        stats=output.stats,
        ingestion_cost=output.ingestion_cost,
        is_shared=output.is_shared,
        owner_tenant_id=output.owner_tenant_id,
        visible_from_tenant_id=output.visible_from_tenant_id,
        share_mode=output.share_mode,
    )


@router.get(
    "/{document_id}/shares",
    response_model=DocumentSharesResponse,
    summary="List Document Shares",
    description="List the tenant targets that can access a default-owned document.",
)
async def list_document_shares(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentSharesResponse:
    from src.core.ingestion.application.document_sharing_service import DocumentSharingService

    _ensure_document_share_management_enabled()
    _require_document_share_manager(http_request)
    service = DocumentSharingService(session)
    try:
        output = await service.list_shares(document_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return _to_document_shares_response(output)


@router.post(
    "/{document_id}/shares",
    response_model=DocumentSharesResponse,
    summary="Add Document Shares",
    description="Add tenant targets that can access a default-owned document.",
)
async def add_document_shares(
    document_id: str,
    payload: DocumentShareRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentSharesResponse:
    from src.core.ingestion.application.document_sharing_service import DocumentSharingService

    _ensure_document_share_management_enabled()
    actor = _require_document_share_manager(http_request)
    service = DocumentSharingService(session)
    try:
        output = await service.add_shares(document_id, payload.tenant_ids, actor=actor)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return _to_document_shares_response(output)


@router.put(
    "/{document_id}/shares",
    response_model=DocumentSharesResponse,
    summary="Replace Document Shares",
    description="Replace the tenant targets that can access a default-owned document.",
)
async def replace_document_shares(
    document_id: str,
    payload: DocumentShareRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentSharesResponse:
    from src.core.ingestion.application.document_sharing_service import DocumentSharingService

    _ensure_document_share_management_enabled()
    actor = _require_document_share_manager(http_request)
    service = DocumentSharingService(session)
    try:
        output = await service.replace_shares(document_id, payload.tenant_ids, actor=actor)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return _to_document_shares_response(output)


@router.delete(
    "/{document_id}/shares",
    response_model=DocumentSharesResponse,
    summary="Remove Document Shares",
    description="Remove tenant targets from a default-owned document share list.",
)
async def remove_document_shares(
    document_id: str,
    payload: DocumentShareRequest = Body(default_factory=DocumentShareRequest),
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentSharesResponse:
    from src.core.ingestion.application.document_sharing_service import DocumentSharingService

    _ensure_document_share_management_enabled()
    actor = _require_document_share_manager(http_request)
    service = DocumentSharingService(session)
    try:
        output = await service.remove_shares(document_id, payload.tenant_ids, actor=actor)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return _to_document_shares_response(output)


@router.get(
    "/{document_id}/communities",
    summary="Get Document Communities",
    description="Get communities (entity clusters) associated with this document.",
)
async def get_document_communities(
    document_id: str,
    limit: int = 50,
    offset: int = 0,
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get communities (entity clusters) for a document from Neo4j.

    Returns communities with their entities, sorted by entity count.
    """
    await _get_visible_document_or_404(document_id, http_request, session)

    from src.core.ingestion.application.use_cases_documents import resolve_graph_document_id

    graph_doc_id = await resolve_graph_document_id(session, document_id)

    # Query Neo4j for communities via BELONGS_TO relationship
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[:MENTIONS]->(e:Entity)-[:BELONGS_TO]->(comm:Community)
        WITH comm, collect(DISTINCT {
            name: e.name,
            type: e.type,
            description: e.description
        }) AS entities
        RETURN comm.id AS community_id, comm.title AS title, comm.summary AS summary,
               comm.level AS level, entities, size(entities) AS entity_count
        ORDER BY entity_count DESC
        SKIP $offset
        LIMIT $limit
    """

    try:
        records = await platform.neo4j_client.execute_read(
            cypher,
            {
                "document_id": graph_doc_id,
                "offset": offset,
                "limit": limit,
            },
        )

        return [
            {
                "community_id": record.get("community_id"),
                "title": record.get("title"),
                "summary": record.get("summary"),
                "level": record.get("level"),
                "entity_count": record.get("entity_count", 0),
                "entities": record.get("entities", []),
            }
            for record in records
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch communities for document {document_id}: {e}")
        return []


@router.get(
    "/{document_id}/file",
    summary="Get Document File",
    description="Download the original document file from storage.",
)
async def get_document_file(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Retrieve the original document file from MinIO storage.

    Returns a streaming response with the file content and appropriate content-type header.
    """
    visible_document = await _get_visible_document_or_404(document_id, http_request, session)
    document = visible_document.document

    # Get file from MinIO
    try:
        storage = platform.minio_client
        # Get the raw stream from MinIO (urllib3 response)
        file_stream = storage.get_file_stream(document.storage_path)

        # Determine content type
        content_type = _get_content_type(document)

        # Stream the file back to the client
        # We pass the stream directly to StreamingResponse
        return StreamingResponse(
            file_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{document.filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    except Exception as e:
        logger.error(f"Failed to retrieve file for document {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve file: {str(e)}",
        ) from e


class DocumentUpdate(BaseModel):
    """Schema for updating a document."""

    title: str | None = None
    folder_id: str | None = None


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Update Document",
    description="Update document details (e.g., title, folder).",
)
async def update_document(
    document_id: str,
    update_data: DocumentUpdate,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    """
    Update a document.
    """
    from src.core.ingestion.application.use_cases_documents import (
        DocumentOutput,
        UpdateDocumentRequest,
        UpdateDocumentUseCase,
    )

    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions
    tenant_id = None
    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)

    use_case = UpdateDocumentUseCase(session=session, graph_client=platform.neo4j_client)
    try:
        output: DocumentOutput = await use_case.execute(
            UpdateDocumentRequest(
                document_id=document_id,
                tenant_id=tenant_id,
                is_super_admin=is_super_admin,
                title=update_data.title,
                folder_id=update_data.folder_id,
            )
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    return DocumentResponse(
        id=output.id,
        filename=output.filename,
        title=output.title,
        status=output.status,
        domain=output.domain,
        tenant_id=output.tenant_id,
        folder_id=output.folder_id,
        source_type=output.source_type,
        content_type=output.content_type,
        created_at=output.created_at,
        summary=output.summary,
        document_type=output.document_type,
        keywords=output.keywords,
        hashtags=output.hashtags,
        metadata=output.metadata,
        stats=output.stats,
        ingestion_cost=output.ingestion_cost,
        is_shared=output.is_shared,
        owner_tenant_id=output.owner_tenant_id,
        visible_from_tenant_id=output.visible_from_tenant_id,
        share_mode=output.share_mode,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Document",
    description="Delete a document from the knowledge base.",
)
async def delete_document(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a document.
    """
    from src.core.ingestion.application.use_cases_documents import (
        DeleteDocumentRequest,
        DeleteDocumentUseCase,
    )

    permissions = getattr(http_request.state, "permissions", [])
    is_super_admin = "super_admin" in permissions

    # 1. Resolve Tenant
    tenant_id = None
    if not is_super_admin:
        tenant_id = _get_tenant_id(http_request)
    else:
        # If super admin, we might need tenant_id?
        # The use case finds document by ID. If super admin, ignores tenant_id.
        # But we still need to pass something for strict typing if expected.
        # Use Case handles it.
        tenant_id = "super_admin_context"

    # 2. Build Dependencies
    # 2. Build Dependencies

    vector_store_factory = build_vector_store_factory()
    dimensions = settings.embedding_dimensions or 1536

    def make_vector_store(tid: str):
        return vector_store_factory(dimensions, collection_name=f"amber_{tid}")

    use_case = DeleteDocumentUseCase(
        session=session,
        storage=platform.minio_client,
        graph_client=platform.neo4j_client,
        vector_store_factory=make_vector_store,
    )

    # 3. Execute
    try:
        await use_case.execute(
            DeleteDocumentRequest(
                document_id=document_id, tenant_id=tenant_id, is_super_admin=is_super_admin
            )
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error deleting document {document_id}: {e}")
        # In case of other errors, we might still want to return 500 or just generic error
        # Use case swallows non-critical errors (graph/milvus cleanup failure),
        # so this catches unexpected ones.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during deletion",
        ) from e

    logger.info(f"Document {document_id} deleted")


@router.get(
    "/{document_id}/entities",
    summary="Get Document Entities",
    description="Get entities extracted from a specific document with pagination.",
)
async def get_document_entities(
    document_id: str,
    limit: int = 100,
    offset: int = 0,
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get entities extracted from a specific document via Neo4j.

    Args:
        document_id: Document UUID
        limit: Maximum number of entities to return (default: 100)
        offset: Number of entities to skip (default: 0)
    """
    await _get_visible_document_or_404(document_id, http_request, session)

    from src.core.ingestion.application.use_cases_documents import resolve_graph_document_id

    graph_doc_id = await resolve_graph_document_id(session, document_id)

    # 2. Query Neo4j with pagination
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[:MENTIONS]->(e:Entity)
        RETURN DISTINCT e
        ORDER BY e.name
        SKIP $offset
        LIMIT $limit
    """

    try:
        records = await platform.neo4j_client.execute_read(
            cypher, {"document_id": graph_doc_id, "limit": limit, "offset": offset}
        )
        # Neo4j Node objects can be converted to dict, but driver returns distinct e as Node.
        # We need to extract properties.
        return [dict(record["e"]) for record in records]
    except Exception as e:
        logger.error(f"Failed to fetch entities for document {document_id}: {e}")
        return []


@router.get(
    "/{document_id}/relationships",
    summary="Get Document Relationships",
    description="Get relationships between entities in this document with pagination.",
)
async def get_document_relationships(
    document_id: str,
    limit: int = 100,
    offset: int = 0,
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get relationships between entities in this document via Neo4j.

    Optimized query that avoids Cartesian products.

    Args:
        document_id: Document UUID
        limit: Maximum number of relationships to return (default: 100)
        offset: Number of relationships to skip (default: 0)
    """
    await _get_visible_document_or_404(document_id, http_request, session)

    from src.core.ingestion.application.use_cases_documents import resolve_graph_document_id

    graph_doc_id = await resolve_graph_document_id(session, document_id)

    # 2. Query Neo4j
    # OPTIMIZED: Direct MATCH pattern instead of UNWIND Cartesian product
    # This is O(N) instead of O(N²) where N is the number of entities
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
        MATCH (c)-[:MENTIONS]->(s:Entity)
        MATCH (s)-[r]->(t:Entity)
        WHERE EXISTS {
              MATCH (d)-[:HAS_CHUNK]->(c2:Chunk)-[:MENTIONS]->(t)
          }
        RETURN DISTINCT {
            source: s.name,
            source_type: s.type,
            target: t.name,
            target_type: t.type,
            type: r.type,
            description: r.description,
            weight: r.weight
        } as rel
        ORDER BY rel.weight DESC
        SKIP $offset
        LIMIT $limit
    """

    try:
        records = await platform.neo4j_client.execute_read(
            cypher, {"document_id": graph_doc_id, "limit": limit, "offset": offset}
        )
        return [record["rel"] for record in records]
    except Exception as e:
        logger.error(f"Failed to fetch relationships for document {document_id}: {e}")
        return []


from src.core.ingestion.domain.chunk import Chunk  # noqa: E402


@router.get(
    "/{document_id}/chunks",
    summary="Get Document Chunks",
    description="Get chunks for a specific document.",
    operation_id="get_document_chunks_simple",
)
async def get_document_chunks(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get chunks for a document from PostgreSQL.
    """
    await _get_visible_document_or_404(document_id, http_request, session)

    # 2. Fetch chunks from Postgres
    chunks_query = select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.index.asc())
    result = await session.execute(chunks_query)
    chunks = result.scalars().all()

    return [
        {
            "id": chunk.id,
            "index": chunk.index,
            "content": chunk.content,
            "tokens": chunk.tokens,
            "embedding_status": chunk.embedding_status.value,
        }
        for chunk in chunks
    ]


@router.get(
    "/{document_id}/similarities",
    summary="Get Document Similarities",
    description="Get similarity relationships between chunks within the document.",
)
async def get_document_similarities(
    document_id: str,
    http_request: Request,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """
    Get similarity relationships between chunks within the document.
    """
    await _get_visible_document_or_404(document_id, http_request, session)

    from src.core.ingestion.application.use_cases_documents import resolve_graph_document_id

    graph_doc_id = await resolve_graph_document_id(session, document_id)

    # Query SIMILAR_TO relationships in Neo4j
    # We want chunk text as well to display in frontend
    # Query SIMILAR_TO relationships in Neo4j
    # We fetch chunk IDs from Neo4j, then texts from Postgres (since Neo4j chunks don't have text)
    cypher = """
        MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c1:Chunk)
        MATCH (c1)-[r:SIMILAR_TO]->(c2:Chunk)
        WHERE c1.id < c2.id
        RETURN c1.id as source_id,
               c2.id as target_id,
               r.score as score
        ORDER BY r.score DESC
        SKIP $offset
        LIMIT $limit
    """

    try:
        # 1. Fetch relations from Neo4j
        records = await platform.neo4j_client.execute_read(
            cypher, {"document_id": graph_doc_id, "offset": offset, "limit": limit}
        )

        if not records:
            return []

        # 2. Collect unique chunk IDs
        chunk_ids = set()
        for r in records:
            chunk_ids.add(r["source_id"])
            chunk_ids.add(r["target_id"])

        # 3. Fetch Chunk text from Postgres
        from src.core.ingestion.domain.chunk import Chunk

        chunk_query = select(Chunk.id, Chunk.content).where(Chunk.id.in_(chunk_ids))
        chunk_result = await session.execute(chunk_query)
        chunk_map = {row.id: row.content for row in chunk_result.all()}

        # 4. Map back to response
        return [
            {
                "source_id": r.get("source_id"),
                "source_text": (chunk_map.get(r.get("source_id")) or "")[:200] + "...",
                "target_id": r.get("target_id"),
                "target_text": (chunk_map.get(r.get("target_id")) or "")[:200] + "...",
                "score": r.get("score"),
            }
            for r in records
        ]

    except Exception as e:
        logger.warning(f"Failed to fetch similarities for document {document_id}: {e}")
        return []
