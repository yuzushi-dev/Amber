"""
Server-Sent Events (SSE) for Document Status
=============================================

Real-time status streaming for document processing.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import redis.asyncio as redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

from src.api.config import settings
from src.api.deps import get_db_session
from src.core.ingestion.domain.document import Document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Events"])


@router.get("/{document_id}/events")
async def stream_document_events(
    document_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """
    Stream document processing events via SSE.

    Subscribes to Redis Pub/Sub channel for the document and streams
    status updates to the client.

    Args:
        document_id: ID of the document to monitor.

    Returns:
        StreamingResponse: SSE stream of status updates.
    """
    if not HAS_REDIS:
        raise HTTPException(status_code=503, detail="Redis not available for SSE")

    # Authenticate and verify document ownership
    tenant_id = getattr(http_request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    is_super_admin = getattr(http_request.state, "is_super_admin", False)
    doc_query = select(Document).where(Document.id == document_id)
    if not is_super_admin:
        doc_query = doc_query.where(Document.tenant_id == tenant_id)
    result = await session.execute(doc_query)
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    return StreamingResponse(
        event_generator(document_id, tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def event_generator(document_id: str, tenant_id: str) -> AsyncGenerator[str, None]:
    """
    Generate SSE events from Redis Pub/Sub.

    Args:
        document_id: Document to monitor.

    Yields:
        str: Formatted SSE event strings.
    """
    channel = f"document:{tenant_id}:{document_id}:status"

    try:
        r = redis.Redis.from_url(settings.db.redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)

        # Send initial connection event
        yield f"event: connected\ndata: {json.dumps({'document_id': document_id})}\n\n"

        # Stream events
        timeout_count = 0
        max_timeouts = 60  # ~5 minutes with 5s timeout

        while timeout_count < max_timeouts:
            message = await asyncio.wait_for(
                pubsub.get_message(ignore_subscribe_messages=True), timeout=5.0
            )

            if message and message.get("type") == "message":
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                yield f"event: status\ndata: {data}\n\n"

                # Check if terminal status
                try:
                    parsed = json.loads(data)
                    if parsed.get("status") in ["ready", "failed", "READY", "FAILED"]:
                        yield f"event: complete\ndata: {data}\n\n"
                        break
                except json.JSONDecodeError:
                    pass

                timeout_count = 0  # Reset on activity
            else:
                timeout_count += 1
                # Send keepalive
                yield ": keepalive\n\n"

    except TimeoutError:
        yield f"event: timeout\ndata: {json.dumps({'document_id': document_id})}\n\n"
    except Exception as e:
        logger.error(f"SSE error for {document_id}: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await r.aclose()
        except Exception:
            pass
