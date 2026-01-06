"""
Tokenizer Utility
=================

Utility for counting tokens using tiktoken (with fallback).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o"
DEFAULT_ENCODING = "cl100k_base"

# Mapping models to their encodings
MODEL_TO_ENCODING = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "claude-3": "cl100k_base",  # Approximate for Claude
}

# Try importing tiktoken
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken not available. Token counting will be estimated.")


class Tokenizer:
    """
    Utility for token counting and text truncation.
    """

    @staticmethod
    def get_encoding(model: str | None = None) -> Any:
        """Get tiktoken encoding for a model."""
        if not TIKTOKEN_AVAILABLE:
            return None

        encoding_name = DEFAULT_ENCODING

        if model:
            # Check direct mapping
            for m, e in MODEL_TO_ENCODING.items():
                if model.startswith(m):
                    encoding_name = e
                    break
            else:
                try:
                    return tiktoken.encoding_for_model(model)
                except Exception:
                    logger.warning(f"Unknown model {model}, using default encoding {DEFAULT_ENCODING}")

        try:
            return tiktoken.get_encoding(encoding_name)
        except Exception:
            return None

    @classmethod
    def count_tokens(cls, text: str, model: str | None = None) -> int:
        """Count tokens in a string for a given model."""
        if not text:
            return 0

        if TIKTOKEN_AVAILABLE:
            try:
                encoding = cls.get_encoding(model)
                if encoding:
                    return len(encoding.encode(text))
            except Exception:
                pass

        # Fallback to rough estimate (4 chars per token)
        return max(1, len(text) // 4)

    @classmethod
    def truncate_to_budget(
        cls,
        text: str,
        max_tokens: int,
        model: str | None = None,
        from_start: bool = True
    ) -> str:
        """Truncate text to fit within a token budget."""
        if not text or max_tokens <= 0:
            return ""

        if TIKTOKEN_AVAILABLE:
            try:
                encoding = cls.get_encoding(model)
                if encoding:
                    tokens = encoding.encode(text)
                    if len(tokens) <= max_tokens:
                        return text

                    if from_start:
                        truncated_tokens = tokens[:max_tokens]
                    else:
                        truncated_tokens = tokens[-max_tokens:]

                    return encoding.decode(truncated_tokens)
            except Exception:
                pass

        # Fallback truncation
        char_limit = max_tokens * 4
        if len(text) <= char_limit:
            return text
        return text[:char_limit] if from_start else text[-char_limit:]
