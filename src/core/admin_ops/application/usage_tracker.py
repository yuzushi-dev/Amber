"""
Usage Tracker Service
=====================

Handles recording of model usage events to the database.
"""

import logging
from typing import Any

import structlog

from src.core.admin_ops.domain.usage import UsageLog
from src.core.generation.domain.provider_models import TokenUsage

logger = structlog.get_logger(__name__)


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
        request_id: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Persists a usage event to the database.
        """
        try:
            logger.debug("record_usage.start", operation=operation, provider=provider, model=model)
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
                    metadata_json=metadata or {},
                )
                session.add(log_entry)
                await session.commit()
                logger.info("record_usage.ok", operation=operation, provider=provider, total_tokens=usage.total_tokens)
                return log_entry.id
        except Exception as e:
            logger.error("record_usage.failed", error=str(e), exc_info=True)
            return None


# Global helper or factory could be added here
