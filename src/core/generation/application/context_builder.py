"""
Context Builder
===============

Builds context for LLM generation from retrieved candidates.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.core.retrieval.domain.candidate import Candidate
from src.core.security.pii_scrubber import PIIScrubber
from src.core.utils.tokenizer import Tokenizer

logger = logging.getLogger(__name__)

@dataclass
class ContextResult:
    """Result of context building."""
    content: str
    tokens: int
    used_candidates: list[Candidate]
    dropped_candidates: list[Candidate]

class ContextBuilder:
    """
    Intelligently packs candidates into the context window.
    """

    def __init__(
        self,
        max_tokens: int = 4000,
        model: str | None = None,
        include_metadata: bool = True
    ):
        self.max_tokens = max_tokens
        self.model = model
        self.include_metadata = include_metadata
        self.pii_scrubber = PIIScrubber()

    def build(self, candidates: list[Any], query: str | None = None) -> ContextResult:
        """
        Build context string from candidates.

        Candidates can be Candidate objects or dictionaries.
        """
        used_candidates = []
        dropped_candidates = []
        current_tokens = 0
        context_parts = []

        # Ensure we're working with a list and candidates have content
        for idx, candidate in enumerate(candidates, 1):
            if isinstance(candidate, dict):
                content = candidate.get("content", "")
                candidate.get("chunk_id", f"chunk_{idx}")
                title = candidate.get("title") or candidate.get("metadata", {}).get("title")
            else:
                # Assume it's a Candidate object from Phase 6
                content = getattr(candidate, "content", "")
                getattr(candidate, "id", f"chunk_{idx}")
                title = getattr(candidate, "metadata", {}).get("title")

            if not content:
                continue

            # Scrub PII from content
            content = self.pii_scrubber.scrub_text(content)

            # Format the candidate part
            header = f"[Source ID: {idx}]"
            if title:
                header += f" [Document: {title}]"

            formatted_part = f"{header}\n{content.strip()}"

            # Count tokens
            part_tokens = Tokenizer.count_tokens(formatted_part, self.model)

            # Check budget
            if current_tokens + part_tokens + 2 <= self.max_tokens: # +2 for newlines
                context_parts.append(formatted_part)
                current_tokens += part_tokens + 2
                used_candidates.append(candidate)
            else:
                # If we're at the limit, we might want to partially include the last one
                # but for simplicity in RAG we usually drop it or truncate at sentence boundary
                remaining_budget = self.max_tokens - current_tokens
                if remaining_budget > 20: # Lowered from 200 to 20 for better small-budget handling
                    truncated_content = self._truncate_at_sentence(content, remaining_budget - 10)
                    if truncated_content:
                        final_part = f"{header}\n{truncated_content}..."
                        context_parts.append(final_part)
                        current_tokens += Tokenizer.count_tokens(final_part, self.model)
                        used_candidates.append(candidate)
                        continue

                dropped_candidates.append(candidate)

        return ContextResult(
            content="\n\n".join(context_parts),
            tokens=current_tokens,
            used_candidates=used_candidates,
            dropped_candidates=dropped_candidates
        )

    def _truncate_at_sentence(self, text: str, max_tokens: int) -> str:
        """Truncates text to fit within max_tokens at the nearest sentence boundary."""
        # Initial truncation by tokens
        rough_truncated = Tokenizer.truncate_to_budget(text, max_tokens, self.model)

        if rough_truncated == text:
            return text

        # Refine to sentence boundary (., !, ?)
        # Look for the last end-of-sentence punctuation in the truncated text
        sentence_end_match = list(re.finditer(r'[.!?](?:\s|$)', rough_truncated))

        if sentence_end_match:
            last_end = sentence_end_match[-1].end()
            return rough_truncated[:last_end].strip()

        return rough_truncated.strip()
