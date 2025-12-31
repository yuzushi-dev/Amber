"""
Event Dispatcher
================

Simple event dispatching for state changes.
"""

from typing import Any
import logging
from dataclasses import dataclass

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

        # Future: publish to Redis message bus
        # redis_client.publish("events", event.json())
