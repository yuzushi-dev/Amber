"""
Rules Service
=============

Manages global rules and their injection into system prompts.
"""

import logging
from typing import Any

from sqlalchemy import select

from src.core.admin_ops.domain.global_rule import GlobalRule
from src.core.tenants.application.effective_config import (
    DEFAULT_TENANT_ID,
    merge_rule_lists,
)

logger = logging.getLogger(__name__)


class RulesService:
    """
    Service for managing and injecting global rules into generation prompts.

    Rules are cached to avoid DB hits on every query.
    Cache is invalidated when rules are modified via API.
    Cache is keyed by tenant_id to prevent cross-tenant rule bleed.
    """

    _rules_cache: dict[str, list[str]] = {}
    _cache_initialized: set[str] = set()

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory

    async def _fetch_active_rules_for_tenant(self, tenant_id: str) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(GlobalRule.content)
                .where(GlobalRule.is_active)
                .where(GlobalRule.tenant_id == tenant_id)
                .order_by(GlobalRule.priority, GlobalRule.created_at)
            )
            return [row[0] for row in result.all()]

    async def get_active_rules(
        self, tenant_id: str = "", force_refresh: bool = False
    ) -> list[str]:
        """
        Fetch all active rules for a tenant, ordered by priority.
        """
        if not force_refresh and tenant_id in RulesService._cache_initialized:
            return RulesService._rules_cache.get(tenant_id, [])

        try:
            default_rules: list[str] = []
            if tenant_id and tenant_id != DEFAULT_TENANT_ID:
                default_rules = await self._fetch_active_rules_for_tenant(DEFAULT_TENANT_ID)

            tenant_rules = await self._fetch_active_rules_for_tenant(tenant_id)
            rules = merge_rule_lists(default_rules, tenant_rules)

            RulesService._rules_cache[tenant_id] = rules
            RulesService._cache_initialized.add(tenant_id)

            logger.debug(f"Loaded {len(rules)} active rules for tenant {tenant_id!r}")
            return rules

        except Exception as e:
            logger.error(f"Failed to fetch rules for tenant {tenant_id!r}: {e}")
            return RulesService._rules_cache.get(tenant_id, [])

    async def build_system_prompt_addendum(self, tenant_id: str = "") -> str:
        """
        Build the rules section to append to the system prompt.
        """
        rules = await self.get_active_rules(tenant_id=tenant_id)

        if not rules:
            return ""

        rules_text = "\n".join([f"- {rule}" for rule in rules])

        return f"""

## DOMAIN RULES
The following rules MUST be considered when answering questions:
{rules_text}
"""

    @classmethod
    def invalidate_cache(cls, tenant_id: str | None = None):
        """
        Invalidate the rules cache.
        """
        if tenant_id is None or tenant_id == DEFAULT_TENANT_ID:
            cls._rules_cache = {}
            cls._cache_initialized = set()
            logger.info("Rules cache fully invalidated")
            return

        cls._rules_cache.pop(tenant_id, None)
        cls._cache_initialized.discard(tenant_id)
        logger.info(f"Rules cache invalidated for tenant {tenant_id!r}")


_rules_service: RulesService | None = None


def get_rules_service() -> RulesService:
    """Get or create the rules service singleton."""
    global _rules_service

    if _rules_service is None:
        from src.core.database.session import async_session_maker

        _rules_service = RulesService(session_factory=async_session_maker)

    return _rules_service
