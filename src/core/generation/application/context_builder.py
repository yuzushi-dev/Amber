"""
Context Builder
===============

Builds context for LLM generation from retrieved candidates.
"""

import logging
import re
from dataclasses import dataclass, field
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
    # Per-candidate accounting only; presented_chars includes the literal "..."
    # suffix when truncated. Never stores source text.
    coverage: list[dict[str, Any]] = field(default_factory=list)
    source_excerpts: dict[int, str] = field(default_factory=dict)


class ContextBuilder:
    """
    Intelligently packs candidates into the context window.
    """

    def __init__(
        self, max_tokens: int = 4000, model: str | None = None, include_metadata: bool = True
    ):
        self.max_tokens = max_tokens
        self.model = model
        self.include_metadata = include_metadata
        self.pii_scrubber = PIIScrubber()

    def build(
        self,
        candidates: list[Any],
        query: str | None = None,
        document_titles: dict[str, str] | None = None,
    ) -> ContextResult:
        """
        Build context string from candidates.

        Candidates can be Candidate objects or dictionaries.
        """
        used_candidates = []
        dropped_candidates = []
        context_parts = []
        coverage = []
        source_excerpts = {}

        # Ensure we're working with a list and candidates have content
        for candidate in candidates:
            if isinstance(candidate, dict):
                raw_content = candidate.get("content", "")
                document_id = candidate.get("document_id")
                metadata = candidate.get("metadata") or candidate
                chunk_id = candidate.get("chunk_id") or candidate.get("id")
                title = (
                    (document_titles or {}).get(document_id)
                    or candidate.get("title")
                    or metadata.get("document_title")
                    or metadata.get("title")
                )
            else:
                raw_content = getattr(candidate, "content", "")
                document_id = getattr(candidate, "document_id", None)
                metadata = getattr(candidate, "metadata", None) or {}
                chunk_id = getattr(candidate, "chunk_id", None) or getattr(candidate, "id", None)
                title = (
                    (document_titles or {}).get(document_id)
                    or metadata.get("document_title")
                    or metadata.get("title")
                )

            raw_content = str(raw_content or "")
            synthetic = bool(metadata.get("synthetic"))
            if not raw_content:
                coverage.append(
                    self._coverage_record(
                        chunk_id, document_id, None, 0, 0, 0, False, True,
                        "empty_content", synthetic,
                    )
                )
                continue

            # Scrub PII from content
            content = self.pii_scrubber.scrub_text(raw_content)
            if not content:
                coverage.append(
                    self._coverage_record(
                        chunk_id, document_id, None, len(raw_content), 0, 0,
                        False, True, "empty_after_pii", synthetic,
                    )
                )
                continue

            # Format the candidate part
            source_id = len(used_candidates) + 1
            header = f"[Source ID: {source_id}]"
            if document_id:
                header += f" [Document ID: {document_id}]"
            if title:
                header += f" [Document: {title}]"

            # Add context metadata if available (Phase 2 - Context Disambiguation)
            product = metadata.get("product_context")
            audience = metadata.get("audience")

            if product:
                header += f" [Product: {product}]"
            if audience:
                header += f" [Audience: {audience}]"

            formatted_part = f"{header}\n{content}"

            # Count the complete assembled context so headers, separators, and
            # tokenizer non-additivity are included in the actual budget.
            full_context = self._assemble(context_parts, formatted_part)
            if Tokenizer.count_tokens(full_context, self.model) <= self.max_tokens:
                context_parts.append(formatted_part)
                used_candidates.append(candidate)
                if not synthetic:
                    source_excerpts[source_id] = content
                coverage.append(
                    self._coverage_record(
                        chunk_id, document_id, source_id, len(raw_content),
                        len(content), len(content), False, False, "included", synthetic,
                    )
                )
            else:
                current_tokens = Tokenizer.count_tokens(self._assemble(context_parts), self.model)
                remaining_budget = self.max_tokens - current_tokens
                accepted_part = None
                accepted_content = ""
                # Preserve the historical small-remainder gate. Include the
                # actual assembled header/newline/ellipsis overhead before
                # choosing the first body budget.
                if remaining_budget > 20:
                    base_context = self._assemble(context_parts)
                    base_tokens = Tokenizer.count_tokens(base_context, self.model)
                    empty_part = f"{header}\n..."
                    overhead = (
                        Tokenizer.count_tokens(self._assemble(context_parts, empty_part), self.model)
                        - base_tokens
                    )
                    attempt_budget = max(0, self.max_tokens - base_tokens - overhead)
                    # ponytail: cap at four attempts; increase only if useful chunks are measurably dropped.
                    for _ in range(4):
                        if attempt_budget <= 0:
                            break
                        truncated_content = self._truncate_at_sentence(content, attempt_budget)
                        if truncated_content and len(truncated_content) < len(content):
                            presented_content = f"{truncated_content}..."
                            trial_part = f"{header}\n{presented_content}"
                            trial_context = self._assemble(context_parts, trial_part)
                            if Tokenizer.count_tokens(trial_context, self.model) <= self.max_tokens:
                                accepted_part = trial_part
                                accepted_content = presented_content
                                break

                            overrun = Tokenizer.count_tokens(trial_context, self.model) - self.max_tokens
                            decrement = max(1, overrun)
                        else:
                            decrement = 1
                        attempt_budget = max(0, attempt_budget - decrement)

                if accepted_part is not None:
                    context_parts.append(accepted_part)
                    used_candidates.append(candidate)
                    if not synthetic:
                        source_excerpts[source_id] = accepted_content[:-3]
                    coverage.append(
                        self._coverage_record(
                            chunk_id, document_id, source_id, len(raw_content),
                            len(content), len(accepted_content), True, False,
                            "truncated", synthetic,
                        )
                    )
                else:
                    dropped_candidates.append(candidate)
                    coverage.append(
                        self._coverage_record(
                            chunk_id, document_id, None, len(raw_content),
                            len(content), 0, False, True, "budget", synthetic,
                        )
                    )

        assembled_context = self._assemble(context_parts)
        return ContextResult(
            content=assembled_context,
            tokens=Tokenizer.count_tokens(assembled_context, self.model),
            used_candidates=used_candidates,
            dropped_candidates=dropped_candidates,
            coverage=coverage,
            source_excerpts=source_excerpts,
        )

    @staticmethod
    def _assemble(context_parts: list[str], additional_part: str | None = None) -> str:
        parts = [*context_parts, additional_part] if additional_part is not None else context_parts
        return "\n\n".join(parts)

    @staticmethod
    def _coverage_record(
        chunk_id: str | None,
        document_id: str | None,
        source_id: int | None,
        original_chars: int,
        post_pii_chars: int,
        presented_chars: int,
        truncated: bool,
        omitted: bool,
        reason: str,
        synthetic: bool,
    ) -> dict[str, Any]:
        return {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "source_id": source_id,
            "original_chars": original_chars,
            "post_pii_chars": post_pii_chars,
            "presented_chars": presented_chars,
            "truncated": truncated,
            "omitted": omitted,
            "reason": reason,
            "synthetic": synthetic,
        }

    def _truncate_at_sentence(self, text: str, max_tokens: int) -> str:
        """Truncates text to fit within max_tokens at the nearest sentence boundary."""
        # Initial truncation by tokens
        rough_truncated = Tokenizer.truncate_to_budget(text, max_tokens, self.model)

        # Tokenizer.decode(errors="ignore") guarantees a true source prefix,
        # even when the final token ends inside a multibyte character.
        if len(rough_truncated) == len(text):
            return rough_truncated

        # Refine to sentence boundary (., !, ?)
        # Look for the last end-of-sentence punctuation in the truncated text
        sentence_end_match = list(re.finditer(r"[.!?](?:\s|$)", rough_truncated))

        if sentence_end_match:
            last_end = sentence_end_match[-1].end()
            return rough_truncated[:last_end]

        return rough_truncated
