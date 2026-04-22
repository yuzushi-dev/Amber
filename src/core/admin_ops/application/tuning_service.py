"""
Tenant Tuning Service
=====================

Handles retrieval of tenant configuration and dynamic weight adjustments.
"""

import json
import logging
from typing import Any

from sqlalchemy.future import select

from src.core.admin_ops.domain.audit import AuditLog
from src.core.generation.domain.provider_models import ProviderTier
from src.core.tenants.application.effective_config import (
    DEFAULT_TENANT_ID,
    merge_tenant_config,
)
from src.core.tenants.domain.tenant import Tenant

logger = logging.getLogger(__name__)


class TuningService:
    """
    Manages per-tenant retrieval settings and dynamic optimization.
    """

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory
        self._config_cache: dict[str, dict[str, Any]] = {}
        self._effective_config_cache: dict[str, dict[str, Any]] = {}

    async def get_tenant_config(self, tenant_id: str) -> dict[str, Any]:
        """Retrieve the raw configuration stored on a tenant."""
        if tenant_id in self._config_cache:
            return self._config_cache[tenant_id]

        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
                tenant = result.scalar_one_or_none()
                if tenant:
                    config = tenant.config or {}
                    self._config_cache[tenant_id] = config
                    return config
        except Exception as e:
            logger.error(f"Failed to fetch tenant config for {tenant_id}: {e}")

        return {}

    async def get_effective_tenant_config(self, tenant_id: str) -> dict[str, Any]:
        """Resolve config inheritance from the default tenant into the current tenant."""
        if tenant_id in self._effective_config_cache:
            return self._effective_config_cache[tenant_id]

        tenant_config = await self.get_tenant_config(tenant_id)
        if tenant_id == DEFAULT_TENANT_ID:
            effective_config = merge_tenant_config({}, tenant_config)
        else:
            default_config = await self.get_tenant_config(DEFAULT_TENANT_ID)
            effective_config = merge_tenant_config(default_config, tenant_config)

        self._effective_config_cache[tenant_id] = effective_config
        return effective_config

    async def update_tenant_weights(self, tenant_id: str, weights: dict[str, float]):
        """
        Updates the retrieval weights for a tenant.
        """
        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
                tenant = result.scalar_one_or_none()
                if tenant:
                    if not tenant.config:
                        tenant.config = {}

                    for k, v in weights.items():
                        tenant.config[f"{k}_weight"] = v

                    session.add(tenant)
                    await session.commit()

                    await self.log_change(
                        tenant_id=tenant_id,
                        actor="system",
                        action="update_weights",
                        target_type="tenant",
                        target_id=tenant_id,
                        changes={"weights": weights},
                    )

                    self.invalidate_cache(tenant_id)
        except Exception as e:
            logger.error(f"Failed to update tenant weights for {tenant_id}: {e}")

    async def log_change(
        self,
        tenant_id: str,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        changes: dict[str, Any],
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
                    changes=changes,
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    async def analyze_feedback_for_tuning(
        self,
        tenant_id: str,
        request_id: str,
        is_positive: bool,
        comment: str | None = None,
        selected_snippets: list[str] | None = None,
    ):
        """
        Analyze feedback to determine if we need to adjust retrieval weights.
        """
        if is_positive:
            logger.info(
                f"Positive feedback for {request_id}. Marking as PENDING for Golden Dataset."
            )
            return

        logger.info(f"Negative feedback received for request {request_id}. Analyzing for tuning...")

        if not comment and not selected_snippets:
            logger.info("No detailed feedback provided. Skipping analysis.")
            return

        try:
            from src.core.generation.application.llm_steps import resolve_llm_step_config
            from src.core.generation.domain.ports.provider_factory import get_provider_factory
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            tenant_config = await self.get_effective_tenant_config(tenant_id)
            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="admin.feedback_analysis",
                settings=settings,
            )
            llm = get_provider_factory().get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.STANDARD,
            )

            snippets_text = (
                "\n".join([f"- {s}" for s in selected_snippets]) if selected_snippets else "None"
            )
            prompt = f"""
            You are an expert RAG system analyzer. A user has provided negative feedback on a generated answer.

            User Comment: "{comment or "No comment"}"
            Flagged Snippets (Incorrect parts):
            {snippets_text}

            Task: Determine if this failure is due to:
            1. RETRIEVAL_FAILURE: The context was missing or irrelevant.
            2. HALLUCINATION: The context was correct, but the LLM made things up.
            3. OTHER: User error, style preference, etc.

            Return JSON only: {{"reason": "RETRIEVAL_FAILURE" | "HALLUCINATION" | "OTHER", "confidence": float, "explanation": string}}
            """

            kwargs: dict[str, Any] = {}
            if llm_cfg.temperature is not None:
                kwargs["temperature"] = llm_cfg.temperature
            if llm_cfg.seed is not None:
                kwargs["seed"] = llm_cfg.seed

            response = await llm.generate(prompt, **kwargs)

            try:
                clean_response = response.replace("```json", "").replace("```", "").strip()
                analysis = json.loads(clean_response)

                logger.info(f"Smart Tuning Analysis: {analysis}")

                if (
                    analysis.get("reason") == "RETRIEVAL_FAILURE"
                    and analysis.get("confidence", 0) > 0.7
                ):
                    logger.info("Detected Retrieval Failure. Suggesting weight adjustment.")
                    logger.info(f"Would increase graph_weight for tenant {tenant_id}")

            except json.JSONDecodeError:
                logger.warning(f"Failed to parse analysis response: {response}")

        except Exception as e:
            logger.error(f"Failed to run smart tuning analysis: {e}")

    def invalidate_cache(self, tenant_id: str):
        """Clear cached config for a tenant, cascading when the default tenant changes."""
        if tenant_id == DEFAULT_TENANT_ID:
            self._config_cache = {}
            self._effective_config_cache = {}
            return

        self._config_cache.pop(tenant_id, None)
        self._effective_config_cache.pop(tenant_id, None)
