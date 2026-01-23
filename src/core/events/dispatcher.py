"""
Event Dispatcher
================

Simple event dispatching for state changes.
"""

import logging
from dataclasses import dataclass
from typing import Any

from src.core.state.machine import DocumentStatus
from src.core.events.ports import StateChangePublisher

logger = logging.getLogger(__name__)


@dataclass
class StateChangeEvent:
    document_id: str
    old_status: DocumentStatus | None
    new_status: DocumentStatus
    tenant_id: str
    details: dict[str, Any] | None = None


class EventDispatcher:
    """
    Handles emission of system events.
    Logs events and publishes via the configured publisher.
    """

    def __init__(self, publisher: StateChangePublisher | None = None) -> None:
        self.publisher = publisher

    async def emit_state_change(self, event: StateChangeEvent) -> None:
        """
        Emit a state change event.

        Args:
            event: The state change event payload
        """
        old_status_val = event.old_status.value if event.old_status else "None"
        logger.info(
            f"State Change [Doc: {event.document_id}] "
            f"{old_status_val} -> {event.new_status.value}"
        )
        if event.details:
            logger.debug(f"Event details: {event.details}")

        if not self.publisher:
            return

        channel = f"document:{event.document_id}:status"
        message = {
            "document_id": event.document_id,
            "status": event.new_status.value,
            "progress": event.details.get("progress", 0) if event.details else 0,
            "tenant_id": event.tenant_id,
        }
        if event.details:
            message["details"] = event.details

        payload = {"channel": channel, "message": message}
        try:
            await self.publisher.publish(payload)
        except Exception as e:
            logger.warning(f"Failed to publish event: {e}")
