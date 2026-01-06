"""
HyDE (Hypothetical Document Embeddings) Service
===============================================

Generates hypothetical answers to bridge query-document semantic gaps.
"""

import logging

import numpy as np

from src.core.prompts.query_analysis import HYDE_PROMPT
from src.core.providers.base import BaseLLMProvider
from src.core.providers.factory import ProviderFactory

logger = logging.getLogger(__name__)


class HyDEService:
    """
    Implements Hypothetical Document Embeddings.
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
            # Use economy tier for HyDE generation
            self.provider = factory.get_llm_provider(model_tier="economy")

    async def generate_hypothesis(
        self,
        query: str,
        n: int = 1,
    ) -> list[str]:
        """
        Generate N hypothetical document segments for a query.
        """
        prompt = HYDE_PROMPT.format(query=query)

        try:
            # If n > 1, we might want parallel generation if the provider supports it,
            # or just loop for now.
            hypotheses = []
            for _ in range(n):
                response = await self.provider.generate(prompt)
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
