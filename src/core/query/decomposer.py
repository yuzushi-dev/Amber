"""
Query Decomposer
================

Uses LLM to split complex queries into atomic sub-queries.
"""

import json
import logging

from src.core.prompts.query_analysis import QUERY_DECOMPOSITION_PROMPT
from src.core.providers.base import BaseLLMProvider
from src.core.providers.factory import ProviderFactory

logger = logging.getLogger(__name__)


class QueryDecomposer:
    """
    Decomposes multi-part or comparative queries into atomic retrieval steps.
    """

    def __init__(
        self,
        provider: BaseLLMProvider | None = None,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
    ):
        if provider:
            self.provider = provider
        else:
            factory = ProviderFactory(
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
            )
            # Use economy tier for decomposition
            self.provider = factory.get_llm_provider(model_tier="economy")

    async def decompose(
        self,
        query: str,
        max_sub_queries: int = 3,
    ) -> list[str]:
        """
        Decompose a query into sub-queries.

        Args:
            query: The complex query to split
            max_sub_queries: Hard limit on number of sub-queries

        Returns:
            List of sub-queries (or [query] if no decomposition needed)
        """
        prompt = QUERY_DECOMPOSITION_PROMPT.format(query=query)

        try:
            response = await self.provider.generate(prompt)

            # Clean response for JSON parsing
            response = response.strip()
            if "```json" in response:
                response = response.split("```json")[-1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[-1].split("```")[0].strip()

            sub_queries = json.loads(response)

            if not isinstance(sub_queries, list):
                logger.warning("Decomposition returned non-list, falling back")
                return [query]

            # Limit number of sub-queries and filter empty ones
            sub_queries = [s.strip() for s in sub_queries if s.strip()][:max_sub_queries]

            return sub_queries or [query]

        except Exception as e:
            logger.error(f"Query decomposition failed: {e}")
            return [query]
