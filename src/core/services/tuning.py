"""
Tenant Tuning Service
=====================

Handles retrieval of tenant configuration and dynamic weight adjustments.
"""

import logging
from typing import Any

from sqlalchemy.future import select

from src.core.models.audit import AuditLog
from src.core.models.tenant import Tenant

logger = logging.getLogger(__name__)

class TuningService:
    """
    Manages per-tenant retrieval settings and dynamic optimization.
    """

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory
        # In-memory cache for configs for performance
        self._config_cache: dict[str, dict[str, Any]] = {}

    async def get_tenant_config(self, tenant_id: str) -> dict[str, Any]:
        """
        Retrieves the configuration for a given tenant.
        """
        if tenant_id in self._config_cache:
            return self._config_cache[tenant_id]

        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = result.scalar_one_or_none()
                if tenant:
                    config = tenant.config or {}
                    self._config_cache[tenant_id] = config
                    return config
        except Exception as e:
            logger.error(f"Failed to fetch tenant config for {tenant_id}: {e}")

        return {}

    async def update_tenant_weights(self, tenant_id: str, weights: dict[str, float]):
        """
        Updates the retrieval weights for a tenant.
        """
        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = result.scalar_one_or_none()
                if tenant:
                    if not tenant.config:
                        tenant.config = {}

                    # Update specific weight keys
                    for k, v in weights.items():
                        tenant.config[f"{k}_weight"] = v

                    session.add(tenant)
                    await session.commit()

                    # Log the change
                    await self.log_change(
                        tenant_id=tenant_id,
                        actor="system",
                        action="update_weights",
                        target_type="tenant",
                        target_id=tenant_id,
                        changes={"weights": weights}
                    )

                    # Invalidate cache
                    if tenant_id in self._config_cache:
                        del self._config_cache[tenant_id]
        except Exception as e:
            logger.error(f"Failed to update tenant weights for {tenant_id}: {e}")

    async def log_change(
        self,
        tenant_id: str,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        changes: dict[str, Any]
    ):
        """Records a change in the audit log."""
        try:
            async with self.session_factory() as session:
                log = AuditLog(
                    tenant_id=tenant_id,
                    actor=actor,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    changes=changes
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    async def analyze_feedback_for_tuning(self, tenant_id: str, request_id: str, is_positive: bool):
        """
        Heuristic: If we get negative feedback on a local search,
        maybe we should increase the graph weight slightly move.
        """
        if is_positive:
            return

        # Simple heuristic for Phase 8 demonstration
        # In a real system, this would aggregate over many requests.
        logger.info(f"Negative feedback received for request {request_id}. Analyzing for tuning...")

        # Example: Slightly bump graph weight if it seems relevant
        # This is a placeholder for a more complex optimization loop (Stage 8.5.2)
        # current_weights = await self.get_tenant_config(tenant_id)
        # new_weights = {"graph": 1.1}
        # await self.update_tenant_weights(tenant_id, new_weights)

    def invalidate_cache(self, tenant_id: str):
        """Clear cached config for a tenant."""
        if tenant_id in self._config_cache:
            del self._config_cache[tenant_id]
