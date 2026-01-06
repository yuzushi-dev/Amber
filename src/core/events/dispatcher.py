"""
Event Dispatcher
================

Simple event dispatching for state changes.
"""

import logging
from dataclasses import dataclass
from typing import Any

from src.core.state.machine import DocumentStatus

logger = logging.getLogger(__name__)


@dataclass
class StateChangeEvent:
    document_id: str
    old_status: DocumentStatus
    new_status: DocumentStatus
    tenant_id: str
    details: dict[str, Any] | None = None


class EventDispatcher:
    """
    Handles emission of system events.
    In Phase 1, this just logs the event.
    In future phases, this will publish to Redis/Celery for async processing.
    """

    @staticmethod
    def emit_state_change(event: StateChangeEvent) -> None:
        """
        Emit a state change event.

        Args:
            event: The state change event payload
        """
        logger.info(
            f"State Change [Doc: {event.document_id}] "
            f"{event.old_status.value} -> {event.new_status.value}"
        )
        if event.details:
            logger.debug(f"Event details: {event.details}")

        # Publish to Redis
        try:
            import json

            import redis

            from src.api.config import settings

            # Use sync Redis client for now as this might be called from sync context
            # or we create a new connection each time. For high throughput, use a pool.
            r = redis.Redis.from_url(settings.db.redis_url)

            channel = f"document:{event.document_id}:status"
            message = {
                "document_id": event.document_id,
                "status": event.new_status.value,
                "progress": event.details.get("progress", 0) if event.details else 0,
                "tenant_id": event.tenant_id
            }
            if event.details:
                message["details"] = event.details

            r.publish(channel, json.dumps(message))
            r.close()

        except Exception as e:
            logger.warning(f"Failed to publish event to Redis: {e}")
