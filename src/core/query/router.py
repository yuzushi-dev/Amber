"""
Query Router
============

Dynamically selects the best SearchMode for a given query.
"""

import logging
from typing import Optional

from src.api.schemas.query import SearchMode
from src.core.providers.base import BaseLLMProvider
from src.core.providers.factory import ProviderFactory
from src.core.prompts.query_analysis import QUERY_MODE_PROMPT

logger = logging.getLogger(__name__)


class QueryRouter:
    """
    Routes queries to the optimal search strategy.
    """

    # Heuristic keywords
    GLOBAL_KEYWORDS = {"all", "main", "themes", "summarize", "trends", "overall", "summary", "everything"}
    DRIFT_KEYWORDS = {"compare", "relation", "differences", "between", "how does", "impact", "influence"}

    def __init__(
        self,
        provider: Optional[BaseLLMProvider] = None,
        openai_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
    ):
        if provider:
            self.provider = provider
        else:
            factory = ProviderFactory(
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
            )
            self.provider = factory.get_llm_provider(model_tier="economy")

    async def route(
        self,
        query: str,
        explicit_mode: Optional[SearchMode] = None,
        use_llm: bool = True,
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
                prompt = QUERY_MODE_PROMPT.format(query=query)
                mode_str = await self.provider.generate(prompt)
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
