"""
Query Rewriter
==============

Uses LLM to rewrite queries into standalone versions using conversation history.
"""

import logging
import time

from src.core.generation.application.prompts.query_analysis import QUERY_REWRITE_PROMPT
from src.core.generation.domain.ports.provider_factory import (
    ProviderFactoryPort,
    build_provider_factory,
    get_provider_factory,
)
from src.core.generation.domain.ports.providers import LLMProviderPort
from src.core.generation.domain.provider_models import ProviderTier

logger = logging.getLogger(__name__)


class QueryRewriter:
    """
    Rewrites ambiguous or context-dependent queries into standalone versions.
    """

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
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            if openai_api_key or anthropic_api_key or settings.ollama_base_url:
                self.factory = build_provider_factory(
                    openai_api_key=openai_api_key,
                    anthropic_api_key=anthropic_api_key,
                    ollama_base_url=settings.ollama_base_url,
                )
            else:
                self.factory = get_provider_factory()

        if provider:
            self.provider = provider
        else:
            self.provider = self.factory.get_llm_provider(model_tier="economy")

    async def rewrite(
        self,
        query: str,
        history: list[dict] | str = "",
        timeout_sec: float = 2.0,
        tenant_config: dict | None = None,
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
            history_str = "\n".join(
                [
                    f"{turn.get('role', 'user').capitalize()}: {turn.get('content', '')}"
                    for turn in history[-5:]  # Use last 5 turns
                ]
            )

        prompt = QUERY_REWRITE_PROMPT.format(history=history_str, query=query)

        start_time = time.perf_counter()
        try:
            from src.core.generation.application.llm_steps import resolve_llm_step_config
            from src.shared.kernel.runtime import get_settings

            settings = get_settings()
            tenant_config = tenant_config or {}
            
            # Resolve Ollama URL from Tenant Config
            res_ollama_url = tenant_config.get("ollama_base_url")
            
            scoped_factory = self.factory
            if res_ollama_url and res_ollama_url != settings.ollama_base_url:
                scoped_factory = build_provider_factory(
                    openai_api_key=settings.openai_api_key,
                    anthropic_api_key=settings.anthropic_api_key,
                    ollama_base_url=res_ollama_url,
                )
            
            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="retrieval.query_rewrite",
                settings=settings,
            )
            provider = scoped_factory.get_llm_provider(
                provider_name=llm_cfg.provider,
                model=llm_cfg.model,
                tier=ProviderTier.ECONOMY,
            )
            kwargs = {}
            if llm_cfg.temperature is not None:
                kwargs["temperature"] = llm_cfg.temperature
            if llm_cfg.seed is not None:
                kwargs["seed"] = llm_cfg.seed

            # We don't have a direct timeout in the provider yet, but we can check after
            rewritten = await provider.generate(prompt, **kwargs)

            elapsed = time.perf_counter() - start_time
            if elapsed > timeout_sec:
                logger.warning(f"Query rewrite took too long ({elapsed:.2f}s), using original")
                return query

            return rewritten.strip()

        except Exception as e:
            logger.error(f"Query rewrite failed: {e}")
            return query
