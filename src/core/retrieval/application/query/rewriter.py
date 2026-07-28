"""
Query Rewriter
==============

Uses LLM to rewrite queries into standalone versions using conversation history.
"""

import asyncio
import logging

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
                    ollama_cloud_base_url=getattr(settings, "ollama_cloud_base_url", None),
                    ollama_cloud_api_keys=getattr(settings, "ollama_cloud_api_keys", None),
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
        history: list[dict] | str | None = None,
        global_rules: list[str] | None = None,
        memory_context: str | None = None,
        timeout_sec: float = 4.5,
        tenant_config: dict | None = None,
    ) -> str:
        """
        Rewrite a query using conversation history.

        Args:
            query: Current user query
            history: List of conversation turns or a formatted string
            timeout_sec: Hard deadline wrapped around the LLM call (asyncio.wait_for);
                on expiry the original query is returned

        Returns:
            Rewritten query or original if failure/timeout
        """
        if not history and not global_rules and not memory_context:
            return query

        # Convert list history to string if needed
        history_str = history or ""
        if isinstance(history, list):
            history_str = "\n".join(
                [
                    f"{turn.get('role', 'user').capitalize()}: {turn.get('content', '')}"
                    for turn in history[-5:]  # Use last 5 turns
                ]
            )

        rules_str = ""
        if global_rules:
            rules_str = "\n".join([f"- {rule}" for rule in global_rules])

        memory_str = memory_context or ""

        prompt = QUERY_REWRITE_PROMPT.format(
            history=history_str,
            query=query,
            rules=rules_str,
            memory=memory_str
        )

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
                    ollama_cloud_base_url=getattr(settings, "ollama_cloud_base_url", None),
                    ollama_cloud_api_keys=getattr(settings, "ollama_cloud_api_keys", None),
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

            try:
                rewritten_res = await asyncio.wait_for(
                    provider.generate(prompt, work_class="chat", **kwargs),
                    timeout=timeout_sec,
                )
            except TimeoutError:
                logger.warning(f"Query rewrite exceeded timeout ({timeout_sec:.2f}s), using original")
                return query

            rewritten = (rewritten_res.text or "").strip()

            if not rewritten:
                logger.warning("Query rewrite returned empty output, using original")
                return query

            max_len = max(200, 4 * len(query))
            if len(rewritten) > max_len:
                logger.warning(
                    f"Query rewrite output disproportionate to input "
                    f"({len(rewritten)} chars > {max_len} limit), using original"
                )
                return query

            return rewritten

        except Exception as e:
            logger.error(f"Query rewrite failed: {e}")
            return query
