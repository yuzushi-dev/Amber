"""
Query Decomposer
================

Uses LLM to split complex queries into atomic sub-queries.
"""

import json
import logging

from src.core.generation.application.prompts.query_analysis import QUERY_DECOMPOSITION_PROMPT
from src.core.generation.domain.ports.provider_factory import (
    ProviderFactoryPort,
    build_provider_factory,
    get_provider_factory,
)
from src.core.generation.domain.ports.providers import LLMProviderPort
from src.core.generation.domain.provider_models import ProviderTier

logger = logging.getLogger(__name__)


class QueryDecomposer:
    """
    Decomposes multi-part or comparative queries into atomic retrieval steps.
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

    async def decompose(
        self,
        query: str,
        max_sub_queries: int = 3,
        tenant_config: dict | None = None,
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
                step_id="retrieval.query_decompose",
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

            response = await provider.generate(prompt, **kwargs)

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
