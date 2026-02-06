"""
Rules Service
=============

Manages global rules and their injection into system prompts.
"""

import logging
from typing import Any

from sqlalchemy import select

from src.core.admin_ops.domain.global_rule import GlobalRule

logger = logging.getLogger(__name__)


class RulesService:
    """
    Service for managing and injecting global rules into generation prompts.

    Rules are cached to avoid DB hits on every query.
    Cache is invalidated when rules are modified via API.
    """

    # Class-level cache (simple in-memory cache)
    _rules_cache: list[str] | None = None
    _cache_initialized: bool = False

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory

    async def get_active_rules(self, force_refresh: bool = False) -> list[str]:
        """
        Fetch all active global rules, ordered by priority.

        Args:
            force_refresh: If True, bypasses cache

        Returns:
            List of rule content strings
        """
        if not force_refresh and RulesService._cache_initialized:
            return RulesService._rules_cache or []

        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(GlobalRule.content)
                    .where(GlobalRule.is_active)
                    .order_by(GlobalRule.priority, GlobalRule.created_at)
                )
                rules = [row[0] for row in result.all()]

                # Update cache
                RulesService._rules_cache = rules
                RulesService._cache_initialized = True

                logger.debug(f"Loaded {len(rules)} active global rules")
                return rules

        except Exception as e:
            logger.error(f"Failed to fetch global rules: {e}")
            return RulesService._rules_cache or []

    async def build_system_prompt_addendum(self) -> str:
        """
        Build the rules section to append to the system prompt.

        Returns:
            Formatted rules string, or empty string if no rules
        """
        rules = await self.get_active_rules()

        if not rules:
            return ""

        rules_text = "\n".join([f"- {rule}" for rule in rules])

        return f"""

## DOMAIN RULES
The following rules MUST be considered when answering questions:
{rules_text}
"""

    @classmethod
    def invalidate_cache(cls):
        """
        Invalidate the rules cache.
        Call this when rules are created, updated, or deleted.
        """
        cls._rules_cache = None
        cls._cache_initialized = False
        logger.info("Rules cache invalidated")


# Singleton instance factory
_rules_service: RulesService | None = None


def get_rules_service() -> RulesService:
    """Get or create the rules service singleton."""
    global _rules_service

    if _rules_service is None:
        from src.core.database.session import async_session_maker

        _rules_service = RulesService(session_factory=async_session_maker)

    return _rules_service
