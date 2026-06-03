"""
Tenant Tuning Service
=====================

Handles retrieval of tenant configuration and dynamic weight adjustments.
"""

import json
import logging
import time
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

# Bounded TTL for in-process config cache entries.  Any replica that missed a
# local invalidate_cache() call (e.g. a config update served by a different
# pod) will self-refresh within this window.
_CONFIG_CACHE_TTL_SECONDS: float = 30.0

# Redis key prefix for the cross-replica version counter.
# On every local config update we INCR this key; readers do a best-effort GET
# and drop their local cache entry when the version has advanced.
_REDIS_VERSION_KEY_PREFIX = "tenant_config_version:"


class TuningService:
    """
    Manages per-tenant retrieval settings and dynamic optimization.
    """

    def __init__(self, session_factory: Any, redis_url: str | None = None):
        self.session_factory = session_factory
        self._redis_url = redis_url
        self._redis: Any | None = None  # redis.asyncio.Redis, lazily created

        # Cache entries: tenant_id → (value, cached_at_monotonic, redis_version_at_cache_time)
        self._config_cache: dict[str, tuple[dict[str, Any], float, int | None]] = {}
        self._effective_config_cache: dict[str, tuple[dict[str, Any], float, int | None]] = {}

    # ------------------------------------------------------------------
    # Redis helpers (best-effort – failures never break the read path)
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Any | None:
        """Return a lazily-created async Redis client, or None if unavailable."""
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        except Exception as exc:
            logger.debug("TuningService: could not create Redis client: %s", exc)
        return self._redis

    async def _get_redis_version(self, tenant_id: str) -> int | None:
        """Best-effort fetch of the cross-replica version counter for *tenant_id*."""
        try:
            client = await self._get_redis()
            if client is None:
                return None
            raw = await client.get(f"{_REDIS_VERSION_KEY_PREFIX}{tenant_id}")
            return int(raw) if raw is not None else 0
        except Exception as exc:
            logger.debug("TuningService: Redis version check failed for %s: %s", tenant_id, exc)
            return None

    async def _bump_redis_version(self, tenant_id: str) -> None:
        """Best-effort INCR of the cross-replica version counter for *tenant_id*."""
        try:
            client = await self._get_redis()
            if client is None:
                return
            key = f"{_REDIS_VERSION_KEY_PREFIX}{tenant_id}"
            await client.incr(key)
            # Also bump the default tenant key when a non-default tenant changes,
            # because effective-config for the default tenant affects all tenants.
            if tenant_id != DEFAULT_TENANT_ID:
                await client.incr(f"{_REDIS_VERSION_KEY_PREFIX}{DEFAULT_TENANT_ID}")
        except Exception as exc:
            logger.debug("TuningService: Redis version bump failed for %s: %s", tenant_id, exc)

    # ------------------------------------------------------------------
    # Cache validity helpers
    # ------------------------------------------------------------------

    async def _is_cache_entry_valid(
        self,
        tenant_id: str,
        cached_at: float,
        cached_version: int | None,
    ) -> bool:
        """
        Return True if the cached entry is still usable.

        An entry is considered stale when:
        - its age exceeds _CONFIG_CACHE_TTL_SECONDS (bounded TTL), OR
        - the Redis version counter has advanced since it was cached (cross-replica signal).
        """
        # TTL check
        if time.monotonic() - cached_at > _CONFIG_CACHE_TTL_SECONDS:
            return False

        # Best-effort Redis version check
        if cached_version is not None:
            current_version = await self._get_redis_version(tenant_id)
            if current_version is not None and current_version != cached_version:
                return False

        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_tenant_config(self, tenant_id: str) -> dict[str, Any]:
        """Retrieve the raw configuration stored on a tenant."""
        entry = self._config_cache.get(tenant_id)
        if entry is not None:
            value, cached_at, cached_version = entry
            if await self._is_cache_entry_valid(tenant_id, cached_at, cached_version):
                return value
            # Stale – evict and re-fetch
            self._config_cache.pop(tenant_id, None)

        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
                tenant = result.scalar_one_or_none()
                if tenant:
                    config = tenant.config or {}
                    redis_version = await self._get_redis_version(tenant_id)
                    self._config_cache[tenant_id] = (config, time.monotonic(), redis_version)
                    return config
        except Exception as e:
            logger.error(f"Failed to fetch tenant config for {tenant_id}: {e}")

        return {}

    async def get_effective_tenant_config(self, tenant_id: str) -> dict[str, Any]:
        """Resolve config inheritance from the default tenant into the current tenant."""
        entry = self._effective_config_cache.get(tenant_id)
        if entry is not None:
            value, cached_at, cached_version = entry
            if await self._is_cache_entry_valid(tenant_id, cached_at, cached_version):
                return value
            # Stale – evict and re-fetch
            self._effective_config_cache.pop(tenant_id, None)

        tenant_config = await self.get_tenant_config(tenant_id)
        if tenant_id == DEFAULT_TENANT_ID:
            effective_config = merge_tenant_config({}, tenant_config)
        else:
            default_config = await self.get_tenant_config(DEFAULT_TENANT_ID)
            effective_config = merge_tenant_config(default_config, tenant_config)

        redis_version = await self._get_redis_version(tenant_id)
        self._effective_config_cache[tenant_id] = (effective_config, time.monotonic(), redis_version)
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
                    # Eagerly await the version bump (we are already in an async
                    # context); invalidate_cache also schedules it, but awaiting
                    # here ensures the key is set before this coroutine returns.
                    await self._bump_redis_version(tenant_id)
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

    def invalidate_cache(self, tenant_id: str) -> None:
        """
        Clear cached config for a tenant locally and signal other replicas via Redis.

        The local invalidation is synchronous (no awaiting).  The Redis version
        bump is fire-and-forget: callers that need the await can call
        _bump_redis_version directly.  Here we schedule it as a best-effort
        background task via asyncio if a loop is running, otherwise skip it.
        """
        if tenant_id == DEFAULT_TENANT_ID:
            self._config_cache = {}
            self._effective_config_cache = {}
        else:
            self._config_cache.pop(tenant_id, None)
            self._effective_config_cache.pop(tenant_id, None)

        # Best-effort: bump the cross-replica Redis version counter.
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._bump_redis_version(tenant_id))
        except RuntimeError:
            # No running event loop (e.g. called from sync context / tests).
            pass
