"""
HyDE (Hypothetical Document Embeddings) Service
===============================================

Generates hypothetical answers to bridge query-document semantic gaps.
"""

import logging

import numpy as np

from src.core.generation.application.prompts.query_analysis import HYDE_PROMPT
from src.core.generation.domain.provider_models import ProviderTier
from src.core.generation.domain.ports.provider_factory import build_provider_factory, get_provider_factory, ProviderFactoryPort
from src.core.generation.domain.ports.providers import LLMProviderPort

logger = logging.getLogger(__name__)


class HyDEService:
    """
    Implements Hypothetical Document Embeddings.
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

    async def generate_hypothesis(
        self,
        query: str,
        n: int = 1,
        tenant_config: dict | None = None,
    ) -> list[str]:
        """
        Generate N hypothetical document segments for a query.
        """
        prompt = HYDE_PROMPT.format(query=query)

        try:
            from src.shared.kernel.runtime import get_settings
            from src.core.generation.application.llm_steps import resolve_llm_step_config

            settings = get_settings()
            tenant_config = tenant_config or {}
            llm_cfg = resolve_llm_step_config(
                tenant_config=tenant_config,
                step_id="retrieval.hyde_generation",
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

            # If n > 1, we might want parallel generation if the provider supports it,
            # or just loop for now.
            hypotheses = []
            for _ in range(n):
                response = await provider.generate(prompt, **kwargs)
                hypotheses.append(response.strip())

            return hypotheses

        except Exception as e:
            logger.error(f"HyDE generation failed: {e}")
            return []

    def validate_consistency(
        self,
        embeddings: list[list[float]],
        threshold: float = 0.7,
    ) -> bool:
        """
        Check if generated hypotheses are semantically consistent.

        Args:
            embeddings: List of embedding vectors for the hypotheses
            threshold: Minimum average cosine similarity to be considered consistent

        Returns:
            True if consistent, False otherwise
        """
        if len(embeddings) < 2:
            return True

        # Convert to numpy for easier calc
        vecs = [np.array(e) for e in embeddings]

        # Calculate pairwise similarities
        sims = []
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                norm_i = np.linalg.norm(vecs[i])
                norm_j = np.linalg.norm(vecs[j])
                if norm_i == 0 or norm_j == 0:
                    sims.append(0.0)
                    continue
                sim = np.dot(vecs[i], vecs[j]) / (norm_i * norm_j)
                sims.append(sim)

        avg_sim = np.mean(sims)
        logger.debug(f"HyDE consistency check: avg_sim={avg_sim:.4f}")

        return avg_sim >= threshold
