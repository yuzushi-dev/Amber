"""
Usage Tracker Service
=====================

Handles recording of model usage events to the database.
"""

import json
import os
from typing import Any

import structlog

from src.core.admin_ops.domain.usage import UsageLog
from src.core.generation.domain.provider_models import TokenUsage
from src.shared.context import get_extra_context

logger = structlog.get_logger(__name__)

# List-price equivalent for models served through the Ollama / Ollama Cloud
# subscription, USD per 1M tokens (input, output). The real cost is the flat
# subscription fee, so rows priced from this table carry
# metadata_json.cost_kind = "subscription_equiv". Same source as the ZTD-2022
# report's prices.json (fetched 2026-09-30). Override or extend with
# AMBER_USAGE_PRICES_JSON='{"model": [input, output]}'.
# ponytail: models without a known list price stay at cost 0, cost_kind "unpriced".
ESTIMATED_PRICES_PER_1M: dict[str, tuple[float, float]] = {
    "gemma4:31b": (0.13, 0.38),  # deepinfra.com/google/gemma-4-31B-it
    "gpt-oss:20b": (0.03, 0.14),  # deepinfra.com/openai/gpt-oss-20b
    "qwen3-next:80b": (0.15, 1.2),  # alibabacloud model-studio pricing
}


def _normalize_model(model: str) -> str:
    """gemma4:31b-cloud / glm-5.2:cloud / x:latest -> the base model name."""
    for suffix in (":latest", ":cloud", "-cloud"):
        if model.endswith(suffix):
            return model[: -len(suffix)]
    return model


def _price_table() -> dict[str, tuple[float, float]]:
    raw = os.environ.get("AMBER_USAGE_PRICES_JSON")
    if not raw:
        return ESTIMATED_PRICES_PER_1M
    try:
        extra = {_normalize_model(k): (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError, IndexError, AttributeError):
        logger.warning("usage_prices.invalid_override", env="AMBER_USAGE_PRICES_JSON")
        return ESTIMATED_PRICES_PER_1M
    return {**ESTIMATED_PRICES_PER_1M, **extra}


def estimate_subscription_cost(model: str, usage: TokenUsage) -> float | None:
    """List-price equivalent in USD, or None when the model has no known price."""
    price = _price_table().get(_normalize_model(model))
    if price is None:
        return None
    return (usage.input_tokens * price[0] + usage.output_tokens * price[1]) / 1_000_000


async def _configure_worker_session(session: Any) -> None:
    """Set GUCs required by FORCE RLS on usage_logs.

    Usage logging is an internal, privileged operation that records events for
    any tenant.  We use the super-admin bypass so the INSERT is never blocked
    by the tenant-isolation policy regardless of which tenant is being logged.
    Mirrors configure_worker_session() from src.core.database.session.
    """
    from sqlalchemy import text

    await session.execute(
        text("SELECT set_config('app.is_super_admin', 'true', false)")
    )
    await session.execute(
        text("SELECT set_config('app.current_tenant', '', false)")
    )


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
            # Caller attribution set by the auth middleware; absent for
            # background work (Celery ingestion, maintenance jobs).
            caller = {k: v for k, v in (get_extra_context() or {}).items() if v}
            metadata = {**caller, **(metadata or {})}
            if operation == "generation" and not cost:
                estimate = estimate_subscription_cost(model, usage)
                if estimate is None:
                    metadata["cost_kind"] = "unpriced"
                else:
                    cost = estimate
                    metadata["cost_kind"] = "subscription_equiv"
            async with self.session_factory() as session:
                await _configure_worker_session(session)
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
                    metadata_json=metadata,
                )
                session.add(log_entry)
                await session.commit()
                logger.info("record_usage.ok", operation=operation, provider=provider, total_tokens=usage.total_tokens)
                return log_entry.id
        except Exception as e:
            logger.error("record_usage.failed", error=str(e), exc_info=True)
            return None


# Global helper or factory could be added here
