"""
Batching Utilities
==================

Token-aware batching for efficient API calls.
"""

import logging
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def get_token_counter(model: str = "gpt-4") -> Callable[[str], int]:
    """
    Get a token counter function for the specified model.

    Falls back to word-based approximation if tiktoken not available.
    """
    try:
        import tiktoken

        # Map model families to encodings
        if "gpt-4" in model or "gpt-3.5" in model:
            encoding = tiktoken.encoding_for_model(model)
        elif "text-embedding" in model:
            encoding = tiktoken.get_encoding("cl100k_base")
        else:
            encoding = tiktoken.get_encoding("cl100k_base")

        return lambda text: len(encoding.encode(text))

    except ImportError:
        logger.warning("tiktoken not available, using word-based approximation")
        # Rough approximation: ~4 chars per token on average
        return lambda text: len(text) // 4


def batch_by_count(
    items: list[T],
    max_batch_size: int,
) -> list[list[T]]:
    """
    Split items into batches of fixed size.

    Args:
        items: List of items to batch
        max_batch_size: Maximum items per batch

    Returns:
        List of batches
    """
    if not items:
        return []

    batches = []
    for i in range(0, len(items), max_batch_size):
        batches.append(items[i : i + max_batch_size])

    return batches


def batch_by_tokens(
    texts: list[str],
    max_tokens_per_batch: int,
    max_items_per_batch: int | None = None,
    token_counter: Callable[[str], int] | None = None,
) -> list[list[tuple[int, str]]]:
    """
    Split texts into batches respecting token limits.

    Args:
        texts: List of texts to batch
        max_tokens_per_batch: Maximum tokens per batch
        max_items_per_batch: Optional maximum items per batch
        token_counter: Function to count tokens (defaults to tiktoken)

    Returns:
        List of batches, each containing (original_index, text) tuples
    """
    if not texts:
        return []

    if token_counter is None:
        token_counter = get_token_counter()

    # Calculate tokens for each text
    indexed_texts = []
    for i, text in enumerate(texts):
        tokens = token_counter(text)
        indexed_texts.append((i, text, tokens))

    batches: list[list[tuple[int, str]]] = []
    current_batch: list[tuple[int, str]] = []
    current_tokens = 0

    for idx, text, tokens in indexed_texts:
        # Check if adding this text would exceed limits
        would_exceed_tokens = current_tokens + tokens > max_tokens_per_batch
        would_exceed_items = (
            max_items_per_batch and len(current_batch) >= max_items_per_batch
        )

        # Start new batch if needed
        if current_batch and (would_exceed_tokens or would_exceed_items):
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        # Handle oversized single items
        if tokens > max_tokens_per_batch:
            logger.warning(
                f"Text at index {idx} ({tokens} tokens) exceeds max batch size "
                f"({max_tokens_per_batch}). Including in its own batch."
            )
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            batches.append([(idx, text)])
            continue

        current_batch.append((idx, text))
        current_tokens += tokens

    # Don't forget the last batch
    if current_batch:
        batches.append(current_batch)

    return batches


def batch_texts_for_embedding(
    texts: list[str],
    model: str = "text-embedding-3-small",
    max_tokens: int = 8000,
    max_items: int = 2048,
) -> list[list[tuple[int, str]]]:
    """
    Batch texts specifically for embedding API calls.

    Args:
        texts: Texts to embed
        model: Embedding model name
        max_tokens: Maximum tokens per batch
        max_items: Maximum items per batch

    Returns:
        Batches with (index, text) tuples
    """
    counter = get_token_counter(model)
    return batch_by_tokens(
        texts=texts,
        max_tokens_per_batch=max_tokens,
        max_items_per_batch=max_items,
        token_counter=counter,
    )


class BatchProcessor:
    """
    Generic batch processor with progress tracking.

    Usage:
        processor = BatchProcessor(
            items=texts,
            batch_size=100,
            process_fn=process_batch,
        )
        results = await processor.process_all()
    """

    def __init__(
        self,
        items: list[Any],
        batch_size: int,
        process_fn: Callable[[list[Any]], Any],
    ):
        self.items = items
        self.batch_size = batch_size
        self.process_fn = process_fn
        self.processed_count = 0
        self.total_count = len(items)

    @property
    def progress(self) -> float:
        """Get progress as a percentage."""
        if self.total_count == 0:
            return 100.0
        return (self.processed_count / self.total_count) * 100

    async def process_all(self) -> list[Any]:
        """Process all items in batches."""
        results = []
        batches = batch_by_count(self.items, self.batch_size)

        for batch in batches:
            result = await self.process_fn(batch)
            results.append(result)
            self.processed_count += len(batch)
            logger.debug(f"Processed batch: {self.progress:.1f}% complete")

        return results
