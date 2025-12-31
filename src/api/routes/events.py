"""
Server-Sent Events (SSE) for Document Status
=============================================

Real-time status streaming for document processing.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

from src.api.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Events"])


@router.get("/{document_id}/events")
async def stream_document_events(document_id: str) -> StreamingResponse:
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
    
    return StreamingResponse(
        event_generator(document_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def event_generator(document_id: str) -> AsyncGenerator[str, None]:
    """
    Generate SSE events from Redis Pub/Sub.
    
    Args:
        document_id: Document to monitor.
        
    Yields:
        str: Formatted SSE event strings.
    """
    channel = f"document:{document_id}:status"
    
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
                pubsub.get_message(ignore_subscribe_messages=True),
                timeout=5.0
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
                
    except asyncio.TimeoutError:
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
