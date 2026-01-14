"""
Tenant Tuning Service
=====================

Handles retrieval of tenant configuration and dynamic weight adjustments.
"""

import logging
from typing import Any

from sqlalchemy.future import select
import json
from src.core.providers.factory import get_llm_provider
from src.core.providers.base import ProviderTier

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

    async def analyze_feedback_for_tuning(
        self, 
        tenant_id: str, 
        request_id: str, 
        is_positive: bool,
        comment: str | None = None,
        selected_snippets: list[str] | None = None
    ):
        """
        Analyze feedback to determine if we need to adjust retrieval weights.
        """
        if is_positive:
            return

        logger.info(f"Negative feedback received for request {request_id}. Analyzing for tuning...")

        # If no comment or snippets, we can't do much deep analysis
        if not comment and not selected_snippets:
            logger.info("No detailed feedback provided. Skipping analysis.")
            return

        try:
            # Stage 1: Get LLM for analysis
            llm = get_llm_provider(tier=ProviderTier.STANDARD)
            
            # Stage 2: Construct Prompt
            snippets_text = "\n".join([f"- {s}" for s in selected_snippets]) if selected_snippets else "None"
            prompt = f"""
            You are an expert RAG system analyzer. A user has provided negative feedback on a generated answer.
            
            User Comment: "{comment or 'No comment'}"
            Flagged Snippets (Incorrect parts):
            {snippets_text}
            
            Task: Determine if this failure is due to:
            1. RETRIEVAL_FAILURE: The context was missing or irrelevant.
            2. HALLUCINATION: The context was correct, but the LLM made things up.
            3. OTHER: User error, style preference, etc.
            
            Return JSON only: {{"reason": "RETRIEVAL_FAILURE" | "HALLUCINATION" | "OTHER", "confidence": float, "explanation": string}}
            """

            # Stage 3: Call LLM
            # Note: We are using a direct generation call here. In a real system, we might use a structured output mode.
            response = await llm.generate(prompt)
            
            # Parse JSON (naive parsing for now)
            try:
                # cleanup markdown code blocks if present
                clean_response = response.replace("```json", "").replace("```", "").strip()
                analysis = json.loads(clean_response)
                
                logger.info(f"Smart Tuning Analysis: {analysis}")

                # Stage 4: Apply Actions (Heuristic)
                if analysis.get("reason") == "RETRIEVAL_FAILURE" and analysis.get("confidence", 0) > 0.7:
                    logger.info("Detected Retrieval Failure. Suggesting weight adjustment.")
                    # Placeholder for actual adjustment logic
                    # current = await self.get_tenant_config(tenant_id)
                    # new_graph_weight = current.get("graph_weight", 1.0) + 0.1
                    # await self.update_tenant_weights(tenant_id, {"graph_weight": new_graph_weight})
                    logger.info(f"Would increase graph_weight for tenant {tenant_id}")

            except json.JSONDecodeError:
                logger.warning(f"Failed to parse analysis response: {response}")

        except Exception as e:
            logger.error(f"Failed to run smart tuning analysis: {e}")

    def invalidate_cache(self, tenant_id: str):
        """Clear cached config for a tenant."""
        if tenant_id in self._config_cache:
            del self._config_cache[tenant_id]
