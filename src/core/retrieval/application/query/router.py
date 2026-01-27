"""
Query Router
============

Dynamically selects the best SearchMode for a given query.
"""

import logging

from src.shared.kernel.models.query import SearchMode
from src.core.generation.application.prompts.query_analysis import QUERY_MODE_PROMPT
from src.core.generation.domain.provider_models import ProviderTier
from src.core.generation.domain.ports.provider_factory import build_provider_factory, get_provider_factory, ProviderFactoryPort
from src.core.generation.domain.ports.providers import LLMProviderPort

logger = logging.getLogger(__name__)


class QueryRouter:
    """
    Routes queries to the optimal search strategy.
    """

    # Heuristic keywords
    GLOBAL_KEYWORDS = {"all", "main", "themes", "summarize", "trends", "overall", "summary", "everything"}
    DRIFT_KEYWORDS = {"compare", "relation", "differences", "between", "how does", "impact", "influence"}

    # Structured query patterns (for list/count operations)
    STRUCTURED_STARTERS = {
        "list", "show", "get", "display", "count", "how many"
    }
    STRUCTURED_TARGETS = {
        "documents", "document", "files", "file",
        "entities", "entity", "relationships", "relationship",
        "chunks", "chunk", "stats", "statistics"
    }

    def __init__(
        self,
        provider: LLMProviderPort | None = None,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        provider_factory: ProviderFactoryPort | None = None,
    ):
        if provider_factory:
            self.factory = provider_factory
        else:
            if openai_api_key or anthropic_api_key:
                self.factory = build_provider_factory(
                    openai_api_key=openai_api_key,
                    anthropic_api_key=anthropic_api_key,
                )
            else:
                self.factory = get_provider_factory()

        if provider:
            self.provider = provider
        else:
            self.provider = self.factory.get_llm_provider(model_tier="economy")

    async def route(
        self,
        query: str,
        explicit_mode: SearchMode | None = None,
        use_llm: bool = True,
        tenant_config: dict | None = None,
    ) -> SearchMode:
        """
        Determine the SearchMode for a query.

        Order of precedence:
        1. Explicit override (from API request)
        2. Rule-based heuristics (Fast)
        3. LLM classification (Smart)
        4. Default (Basic)
        """
        if explicit_mode:
            logger.debug(f"Using explicit search mode: {explicit_mode}")
            return explicit_mode

        # 1. Rule-based heuristics
        query_lower = query.lower()

        # Check for STRUCTURED queries first (list, count, etc.)
        if self._is_structured_query(query_lower):
            logger.debug("Routing to STRUCTURED mode via heuristics")
            return SearchMode.STRUCTURED

        # Check for GLOBAL keywords
        if any(kw in query_lower for kw in self.GLOBAL_KEYWORDS):
            logger.debug("Routing to GLOBAL mode via heuristics")
            return SearchMode.GLOBAL

        # Check for DRIFT keywords (very rough)
        if any(kw in query_lower for kw in self.DRIFT_KEYWORDS):
            logger.debug("Routing to DRIFT mode via heuristics")
            return SearchMode.DRIFT

        # 2. LLM classification
        if use_llm:
            try:
                from src.shared.kernel.runtime import get_settings
                from src.core.generation.application.llm_steps import resolve_llm_step_config

                settings = get_settings()
                tenant_config = tenant_config or {}
                llm_cfg = resolve_llm_step_config(
                    tenant_config=tenant_config,
                    step_id="retrieval.query_router",
                    settings=settings,
                )
                provider = self.factory.get_llm_provider(
                    provider_name=llm_cfg.provider,
                    model=llm_cfg.model,
                    tier=ProviderTier.ECONOMY,
                )
                kwargs = {}
                if llm_cfg.temperature is not None:
                    kwargs["temperature"] = llm_cfg.temperature
                if llm_cfg.seed is not None:
                    kwargs["seed"] = llm_cfg.seed

                prompt = QUERY_MODE_PROMPT.format(query=query)
                mode_str = await provider.generate(prompt, **kwargs)
                mode_str = mode_str.strip().lower()

                if mode_str in [m.value for m in SearchMode]:
                    logger.debug(f"Routing to {mode_str} mode via LLM")
                    return SearchMode.from_str(mode_str) if hasattr(SearchMode, 'from_str') else SearchMode(mode_str)

                logger.warning(f"LLM returned invalid mode: {mode_str}")
            except Exception as e:
                logger.error(f"LLM mode classification failed: {e}")

        # 3. Default
        logger.debug("Falling back to BASIC search mode")
        return SearchMode.BASIC

    def _is_structured_query(self, query_lower: str) -> bool:
        """
        Check if query matches structured query patterns.

        Structured queries are list/count operations on database entities
        that can be answered directly with Cypher, without RAG.
        """
        words = query_lower.split()
        if not words:
            return False

        # Check if starts with a structured starter
        first_word = words[0]
        starts_with_starter = first_word in self.STRUCTURED_STARTERS

        # Special case: "how many" is two words
        starts_with_how_many = (
            len(words) >= 2 and
            words[0] == "how" and
            words[1] == "many"
        )

        if not (starts_with_starter or starts_with_how_many):
            return False

        # Check if any word matches a structured target
        return any(word in self.STRUCTURED_TARGETS for word in words)
