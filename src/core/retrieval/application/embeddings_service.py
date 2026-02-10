"""
Embedding Service
=================

High-level service for generating and managing embeddings.
Handles batching, retries, and provider failover.
"""

import logging
from dataclasses import dataclass
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.generation.domain.ports.provider_factory import (
    build_provider_factory,
    get_provider_factory,
)
from src.core.generation.domain.ports.providers import EmbeddingProviderPort
from src.core.generation.domain.provider_models import (
    EmbeddingResult,
    ProviderUnavailableError,
    RateLimitError,
)
from src.core.utils.batching import batch_texts_for_embedding

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingStats:
    """Statistics for an embedding operation."""

    total_texts: int = 0
    total_batches: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    total_cost: float = 0.0
    failed_texts: int = 0


class EmbeddingService:
    """
    Service for generating embeddings with production-grade reliability.

    Features:
    - Token-aware batching
    - Exponential backoff retries
    - Provider failover
    - Cost & latency tracking

    Usage:
        service = EmbeddingService(
            openai_api_key="sk-...",
        )
        embeddings = await service.embed_texts(["Hello", "World"])
    """

    # Default batch limits
    MAX_TOKENS_PER_BATCH = 8000
    MAX_ITEMS_PER_BATCH = 2048

    # Retry configuration
    MAX_RETRIES = 5
    RETRY_MIN_WAIT = 1.0  # seconds
    RETRY_MAX_WAIT = 60.0  # seconds

    def __init__(
        self,
        provider: EmbeddingProviderPort | None = None,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        ollama_base_url: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        max_tokens_per_batch: int | None = None,
        max_items_per_batch: int | None = None,
    ):
        """
        Initialize the embedding service.

        Args:
            provider: Pre-configured provider (optional)
            openai_api_key: OpenAI API key
            anthropic_api_key: Anthropic API key (for future use)
            ollama_base_url: Ollama Base URL (optional)
            model: Default embedding model (defaults to provider default)
            dimensions: Optional dimension reduction
            max_tokens_per_batch: Override default batch token limit
            max_items_per_batch: Override default batch item limit
        """
        if provider:
            self.provider = provider
        else:
            if openai_api_key or anthropic_api_key or ollama_base_url:
                factory = build_provider_factory(
                    openai_api_key=openai_api_key,
                    anthropic_api_key=anthropic_api_key,
                    ollama_base_url=ollama_base_url,
                )
            else:
                from src.shared.kernel.runtime import get_settings

                settings = get_settings()
                if settings.ollama_base_url:
                    factory = build_provider_factory(
                        openai_api_key=openai_api_key,
                        anthropic_api_key=anthropic_api_key,
                        ollama_base_url=settings.ollama_base_url,
                    )
                else:
                    factory = get_provider_factory()
            self.provider = factory.get_embedding_provider()

        self.model = model or getattr(
            self.provider, "default_model", self.provider.get_default_model()
        )
        self.dimensions = dimensions
        self.max_tokens = max_tokens_per_batch or self.MAX_TOKENS_PER_BATCH
        self.max_items = max_items_per_batch or self.MAX_ITEMS_PER_BATCH

    async def embed_texts(
        self,
        texts: list[str],
        model: str | None = None,
        dimensions: int | None = None,
        show_progress: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list[list[float]], EmbeddingStats]:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: Texts to embed
            model: Override default model
            dimensions: Override default dimensions
            show_progress: Log progress updates

        Returns:
            Tuple of (embeddings, stats)
            Embeddings are in same order as input texts
        """
        if not texts:
            return [], EmbeddingStats()

        model = model or self.model
        dimensions = dimensions or self.dimensions

        # Batch the texts
        batches = batch_texts_for_embedding(
            texts=texts,
            model=model,
            max_tokens=self.max_tokens,
            max_items=self.max_items,
        )

        stats = EmbeddingStats(
            total_texts=len(texts),
            total_batches=len(batches),
        )

        # Pre-allocate result array
        embeddings: list[list[float] | None] = [None] * len(texts)

        # Process batches
        for batch_idx, batch in enumerate(batches):
            if show_progress:
                logger.info(f"Processing batch {batch_idx + 1}/{len(batches)}")

            # Extract texts for this batch
            batch_texts = [text for _, text in batch]

            # Embed with retries
            # If this fails, we want it to raise an exception so the document fails
            # with a meaningful error (e.g. AuthError) instead of a confusing Milvus error later.
            result = await self._embed_batch_with_retry(
                texts=batch_texts,
                model=model,
                dimensions=dimensions,
                metadata=metadata,
            )

            # Place results in correct positions
            for i, (original_idx, _) in enumerate(batch):
                embeddings[original_idx] = result.embeddings[i]

            # Update stats
            stats.total_tokens += result.usage.input_tokens
            stats.total_latency_ms += result.latency_ms
            stats.total_cost += result.cost_estimate

        # Filter out None values (shouldn't happen but be safe)
        final_embeddings = [e if e is not None else [] for e in embeddings]

        return final_embeddings, stats

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        retry=retry_if_exception_type((RateLimitError, ProviderUnavailableError)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying embedding after {retry_state.outcome.exception()}"
        ),
    )
    async def _embed_batch_with_retry(
        self,
        texts: list[str],
        model: str,
        dimensions: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> EmbeddingResult:
        """Embed a batch with automatic retries."""
        return await self.provider.embed(
            texts=texts,
            model=model,
            dimensions=dimensions,
            metadata=metadata,
        )

    async def embed_single(
        self,
        text: str,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> list[float]:
        """
        Embed a single text.

        Convenience method for single embeddings.
        """
        embeddings, _ = await self.embed_texts(
            texts=[text],
            model=model,
            dimensions=dimensions,
        )
        return embeddings[0] if embeddings else []

    def get_dimensions(self, model: str | None = None) -> int:
        """Get the embedding dimensions for the current model."""
        model = model or self.model
        if self.dimensions:
            return self.dimensions
        return self.provider.get_dimensions(model)


# =============================================================================
# Document Embedding Integration
# =============================================================================


async def process_document_embeddings(
    document_id: str,
    chunks: list[dict[str, Any]],
    embedding_service: EmbeddingService,
    update_callback: Any | None = None,
) -> dict[str, list[float]]:
    """
    Process embeddings for document chunks.

    Args:
        document_id: Document ID for logging
        chunks: List of chunk dicts with 'id' and 'content' keys
        embedding_service: Configured embedding service
        update_callback: Optional callback for progress updates

    Returns:
        Dict mapping chunk_id -> embedding
    """
    if not chunks:
        return {}

    logger.info(f"Generating embeddings for {len(chunks)} chunks from document {document_id}")

    # Extract texts maintaining order
    chunk_ids = [c["id"] for c in chunks]
    texts = [c["content"] for c in chunks]

    # Generate embeddings
    embeddings, stats = await embedding_service.embed_texts(
        texts=texts,
        show_progress=True,
    )

    logger.info(
        f"Completed embeddings for document {document_id}: "
        f"{stats.total_tokens} tokens, {stats.total_latency_ms:.0f}ms, "
        f"${stats.total_cost:.6f}"
    )

    if stats.failed_texts > 0:
        logger.warning(f"{stats.failed_texts} chunks failed to embed")

    # Build result mapping
    return {
        chunk_id: embedding
        for chunk_id, embedding in zip(chunk_ids, embeddings, strict=False)
        if embedding  # Skip failed embeddings
    }
