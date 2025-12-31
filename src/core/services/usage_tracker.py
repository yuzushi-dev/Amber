"""
Usage Tracker Service
=====================

Handles recording of model usage events to the database.
"""

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from src.core.models.usage import UsageLog
from src.core.providers.base import TokenUsage

logger = logging.getLogger(__name__)

class UsageTracker:
    """
    Asynchronous service to record model usage events.
    """

    def __init__(self, session_factory: Any):
        """
        Args:
            session_factory: Callable that returns an AsyncSession or a session manager.
        """
        self.session_factory = session_factory

    async def record_usage(
        self,
        tenant_id: str,
        operation: str,
        provider: str,
        model: str,
        usage: TokenUsage,
        cost: float = 0.0,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Persists a usage event to the database.
        """
        try:
            async with self.session_factory() as session:
                log_entry = UsageLog(
                    tenant_id=tenant_id,
                    operation=operation,
                    provider=provider,
                    model=model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    cost=cost,
                    request_id=request_id,
                    trace_id=trace_id,
                    metadata_json=metadata or {}
                )
                session.add(log_entry)
                await session.commit()
                return log_entry.id
        except Exception as e:
            logger.error(f"Failed to record usage log: {e}")
            return None

# Global helper or factory could be added here
