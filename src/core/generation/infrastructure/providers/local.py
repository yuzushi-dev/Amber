"""
Local Providers
===============

Self-hosted providers using sentence-transformers and local models.
No API costs, works offline, privacy-preserving.
"""

import logging
import time
from typing import Any

from src.core.generation.infrastructure.providers.base import (
    BaseEmbeddingProvider,
    BaseRerankerProvider,
    EmbeddingResult,
    ProviderConfig,
    ProviderUnavailableError,
    RerankResult,
    TokenUsage,
)

logger = logging.getLogger(__name__)

# Lazy load models to avoid memory usage if not needed
_embedding_model = None
_reranker_model = None


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """
    Local embedding provider using sentence-transformers.

    Uses BGE-M3 by default for multilingual support.
    Works offline, no API costs.
    """

    provider_name = "local"

    models = {
        "BAAI/bge-m3": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,  # Free
            "description": "Multilingual, high-quality local embeddings",
        },
        "BAAI/bge-large-en-v1.5": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,
            "description": "English-focused, high quality",
        },
        "BAAI/bge-small-en-v1.5": {
            "dimensions": 384,
            "max_dimensions": 384,
            "cost_per_1k": 0.0,
            "description": "Fast, lightweight embeddings",
        },
        "sentence-transformers/all-MiniLM-L6-v2": {
            "dimensions": 384,
            "max_dimensions": 384,
            "cost_per_1k": 0.0,
            "description": "Popular lightweight model",
        },
    }

    default_model = "BAAI/bge-m3"

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        self._model = None
        self._model_name = None

    def _validate_config(self):
        """Validate local provider config."""
        # Local provider doesn't require keys
        pass

    def _load_model(self, model_name: str):
        """Lazily load the sentence-transformers model."""
        if self._model is not None and self._model_name == model_name:
            return self._model

        try:
            import torch
            from sentence_transformers import SentenceTransformer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Loading local embedding model: {model_name} on device: {device}")
            self._model = SentenceTransformer(model_name, device=device)
            self._model_name = model_name
            return self._model

        except ImportError as e:
            raise ImportError(
                "sentence-transformers package is required for local embeddings. "
                "Install with: pip install sentence-transformers>=2.7.0"
            ) from e
        except Exception as e:
            raise ProviderUnavailableError(
                f"Failed to load model {model_name}: {e}",
                provider=self.provider_name,
                model=model_name,
            ) from e

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        dimensions: int | None = None,
        **kwargs: Any,
    ) -> EmbeddingResult:
        """Generate embeddings using local model."""
        model_name = model or self.default_model
        start_time = time.perf_counter()

        try:
            encoder = self._load_model(model_name)

            # Generate embeddings (runs synchronously, but fast locally)
            import asyncio

            embeddings = await asyncio.get_event_loop().run_in_executor(
                None, lambda: encoder.encode(texts, convert_to_numpy=True).tolist()
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Apply dimension reduction if requested
            actual_dims = len(embeddings[0]) if embeddings else 0
            if dimensions and dimensions < actual_dims:
                embeddings = [e[:dimensions] for e in embeddings]
                actual_dims = dimensions

            return EmbeddingResult(
                embeddings=embeddings,
                model=model_name,
                provider=self.provider_name,
                usage=TokenUsage(input_tokens=sum(len(t.split()) for t in texts)),  # Approximate
                dimensions=actual_dims,
                latency_ms=elapsed_ms,
                cost_estimate=0.0,  # Always free
            )

        except Exception as e:
            if "ImportError" in str(type(e).__name__):
                raise
            raise ProviderUnavailableError(
                f"Embedding failed: {e}",
                provider=self.provider_name,
                model=model_name,
            ) from e


class FlashRankReranker(BaseRerankerProvider):
    """
    Local reranker using FlashRank.

    Ultra-fast, CPU-friendly reranking.
    """

    provider_name = "flashrank"

    models = {
        "ms-marco-MiniLM-L-12-v2": {
            "description": "Default FlashRank model",
        },
        "ms-marco-MultiBERT-L-12": {
            "description": "Multilingual support",
        },
    }

    default_model = "ms-marco-MiniLM-L-12-v2"

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        self._ranker = None

    def _load_ranker(self, model_name: str):
        """Lazily load FlashRank ranker."""
        if self._ranker is not None:
            return self._ranker

        try:
            from flashrank import Ranker
            # from flashrank import RerankRequest # Unused

            logger.info(f"Loading FlashRank reranker: {model_name}")
            self._ranker = Ranker(model_name=model_name)
            return self._ranker

        except ImportError as e:
            raise ImportError(
                "flashrank package is required. Install with: pip install flashrank>=0.2.0"
            ) from e

    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> RerankResult:
        """Rerank documents using FlashRank."""
        model_name = model or self.default_model
        start_time = time.perf_counter()

        try:
            ranker = self._load_ranker(model_name)
            from flashrank import RerankRequest

            # FlashRank expects list of dicts with 'text' key
            passages = [{"id": i, "text": doc} for i, doc in enumerate(documents)]
            request = RerankRequest(query=query, passages=passages)

            import asyncio

            results = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ranker.rerank(request)
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Convert to our format
            scored_items = [
                RerankResult.ScoredItem(
                    index=r["id"],
                    score=r["score"],
                    text=r.get("text"),
                )
                for r in results
            ]

            # Apply top_k if specified
            if top_k:
                scored_items = scored_items[:top_k]

            return RerankResult(
                results=scored_items,
                model=model_name,
                provider=self.provider_name,
                latency_ms=elapsed_ms,
            )

        except ImportError:
            raise
        except Exception as e:
            raise ProviderUnavailableError(
                f"Reranking failed: {e}",
                provider=self.provider_name,
                model=model_name,
            ) from e
