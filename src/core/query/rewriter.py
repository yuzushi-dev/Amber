"""
Query Rewriter
==============

Uses LLM to rewrite queries into standalone versions using conversation history.
"""

import logging
import time
from typing import List, Optional

from src.core.providers.base import BaseLLMProvider
from src.core.providers.factory import ProviderFactory
from src.core.prompts.query_analysis import QUERY_REWRITE_PROMPT

logger = logging.getLogger(__name__)


class QueryRewriter:
    """
    Rewrites ambiguous or context-dependent queries into standalone versions.
    """

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
            # Use economy tier for rewriting
            self.provider = factory.get_llm_provider(model_tier="economy")

    async def rewrite(
        self,
        query: str,
        history: List[dict] | str = "",
        timeout_sec: float = 2.0,
    ) -> str:
        """
        Rewrite a query using conversation history.
        
        Args:
            query: Current user query
            history: List of conversation turns or a formatted string
            timeout_sec: Latency guard, return original if exceeds
            
        Returns:
            Rewritten query or original if failure/timeout
        """
        if not history:
            return query

        # Convert list history to string if needed
        history_str = history
        if isinstance(history, list):
            history_str = "\n".join([
                f"{turn.get('role', 'user').capitalize()}: {turn.get('content', '')}"
                for turn in history[-5:]  # Use last 5 turns
            ])

        prompt = QUERY_REWRITE_PROMPT.format(history=history_str, query=query)
        
        start_time = time.perf_counter()
        try:
            # We don't have a direct timeout in the provider yet, but we can check after
            rewritten = await self.provider.generate(prompt)
            
            elapsed = time.perf_counter() - start_time
            if elapsed > timeout_sec:
                logger.warning(f"Query rewrite took too long ({elapsed:.2f}s), using original")
                return query
                
            return rewritten.strip()
            
        except Exception as e:
            logger.error(f"Query rewrite failed: {e}")
            return query
