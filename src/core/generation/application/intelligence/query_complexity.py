"""
Query Complexity Router
=======================

Classifies an incoming RAG query into one of four tiers (simple / standard /
complex / reasoning) using a weighted combination of query-linguistic signals
and RAG-context signals.

All signals are computed locally with zero LLM calls.  The RAG-context signals
(distinct document count, chunk count, context tokens) are the unique advantage
over generic routers like Manifest — they are only available after retrieval.

Tier → recommended use:
  SIMPLE    — FAQ, single-fact lookup, definition retrieval
  STANDARD  — Procedural info, lightweight comparison across 2 concepts
  COMPLEX   — Multi-document comparison, cross-document analysis
  REASONING — Strategic synthesis, risk analysis, cross-domain compliance planning
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class QueryTier(StrEnum):
    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"
    REASONING = "reasoning"


@dataclass(frozen=True)
class ComplexitySignals:
    # Query linguistic signals
    word_count: int
    has_comparison: bool
    has_synthesis: bool
    has_all_docs_signal: bool
    has_risk_compliance: bool
    has_multi_task: bool
    # RAG context signals
    num_distinct_documents: int
    num_chunks: int
    context_tokens: int
    # Computed
    score: float  # 0-100


# ---------------------------------------------------------------------------
# Keyword sets (substring match — handles Italian morphology)
# ---------------------------------------------------------------------------

_COMPARISON_IT = {
    "confronta", "differenz", "paragona", "contrapponi",
    "rispetto a", "in confronto", "a differenza",
}
_COMPARISON_EN = {
    "compare", "contrast", "difference", "versus", " vs ",
    "compared to", "in contrast",
}

_SYNTHESIS_IT = {
    "sviluppa", "crea un piano", "proponi", "strategi",
    "piano d", "progetta", "definisci un", "redigi",
}
_SYNTHESIS_EN = {
    "develop", "create a plan", "propose", "strategy",
    "design a", "draft a", "recommend a",
}

_ALL_DOCS_IT = {
    "tutti i documenti", "tutti i contratti", "ogni documento",
    "analizza tutti", "tutti i file", "tutta la documentazione",
    "tra le policy", "tra i contratti", "interdipendenz",
}
_ALL_DOCS_EN = {
    "all documents", "all contracts", "every document",
    "analyze all", "all files", "across all",
    "between the policies", "among the contracts",
}

_RISK_IT = {
    "rischio", "compliance", "conformità", "violazione",
    "vulnerabilit", "esposizione", "inadempimento", "normat",
}
_RISK_EN = {
    "risk", "compliance", "violation", "vulnerability",
    "exposure", "breach", "non-compliance", "regulatory",
}


def _matches_any(text: str, keywords: set[str]) -> bool:
    return any(kw in text for kw in keywords)


def _has_multi_task(text: str) -> bool:
    """
    True when the query contains 3+ distinct sub-tasks.

    Patterns detected:
    - "for: A, B, C"  /  "for A, B, and C"  (colon-list or enumeration after "for")
    - "how to X, how to Y, how to Z"  (repeated how-to)
    - 3+ comma-separated noun phrases after action verbs (configure, enable, set up)
    """
    import re

    # Pattern 1: "for: item1, item2, item3" or "for item1, item2, and item3"
    colon_list = re.search(r"\bfor\s*:\s*[^.?!,]+,\s*[^.?!,]+,", text)
    if colon_list:
        return True

    # Pattern 2: action verb + 3+ comma items
    # "configure X for autoprovisioning, authentication, external GAL"
    action_list = re.search(
        r"\b(?:configure|enable|set up|install|setup|integrate|deploy)\b"
        r"(?:.{1,60}),(?:.{1,60}),",
        text,
    )
    if action_list:
        return True

    # Pattern 3: three or more "how to" occurrences
    if len(re.findall(r"\bhow\s+to\b", text)) >= 2:
        return True

    return False


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_W_WORD_COUNT_LG = 8        # query >= 20 words
_W_COMPARISON = 20          # explicit compare/contrast intent
_W_SYNTHESIS = 25           # planning/development intent
_W_ALL_DOCS = 20            # "all documents / tutti i documenti"
_W_RISK = 10                # risk or compliance keywords
_W_MULTI_TASK = 17          # 3+ sub-tasks in a single query

_W_DOCS_2 = 10              # 2+ distinct docs
_W_DOCS_3 = 10              # 3+ distinct docs (cumulative)
_W_DOCS_5 = 10              # 5+ distinct docs (cumulative)

_W_CHUNKS_8 = 8             # 8+ chunks
_W_CHUNKS_15 = 5            # 15+ chunks (cumulative)

_W_TOKENS_3K = 8            # 3000+ context tokens
_W_TOKENS_6K = 5            # 6000+ context tokens (cumulative)


# ---------------------------------------------------------------------------
# Tier thresholds
# ---------------------------------------------------------------------------

_TIER_SIMPLE = 20
_TIER_STANDARD = 50
_TIER_COMPLEX = 80


class QueryComplexityRouter:
    """
    Scores a (query, retrieved_candidates, context_tokens) triple and returns
    the appropriate complexity tier.
    """

    def classify(
        self,
        query: str,
        candidates: list[Any],
        context_tokens: int,
    ) -> QueryTier:
        _, signals = self.classify_with_signals(query, candidates, context_tokens)
        return _score_to_tier(signals.score)

    def classify_with_signals(
        self,
        query: str,
        candidates: list[Any],
        context_tokens: int,
    ) -> tuple[QueryTier, ComplexitySignals]:
        signals = _compute_signals(query, candidates, context_tokens)
        return _score_to_tier(signals.score), signals


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_distinct_documents(candidates: list[Any]) -> int:
    doc_ids: set[str] = set()
    for c in candidates:
        if isinstance(c, dict):
            doc_id = (
                c.get("document_id")
                or (c.get("metadata") or {}).get("document_id")
            )
        else:
            doc_id = getattr(c, "document_id", None) or getattr(
                getattr(c, "metadata", {}), "document_id", None
            )
        if doc_id:
            doc_ids.add(str(doc_id))
    return len(doc_ids)


def _compute_signals(
    query: str,
    candidates: list[Any],
    context_tokens: int,
) -> ComplexitySignals:
    q = query.lower()

    word_count = len(re.split(r"\s+", query.strip()))
    has_comparison = _matches_any(q, _COMPARISON_IT | _COMPARISON_EN)
    has_synthesis = _matches_any(q, _SYNTHESIS_IT | _SYNTHESIS_EN)
    has_all_docs = _matches_any(q, _ALL_DOCS_IT | _ALL_DOCS_EN)
    has_risk = _matches_any(q, _RISK_IT | _RISK_EN)
    has_mt = _has_multi_task(q)

    num_docs = _count_distinct_documents(candidates)
    num_chunks = len(candidates)

    score = 0.0
    if word_count >= 20:
        score += _W_WORD_COUNT_LG
    if has_comparison:
        score += _W_COMPARISON
    if has_synthesis:
        score += _W_SYNTHESIS
    if has_all_docs:
        score += _W_ALL_DOCS
    if has_risk:
        score += _W_RISK
    if has_mt:
        score += _W_MULTI_TASK

    if num_docs >= 2:
        score += _W_DOCS_2
    if num_docs >= 3:
        score += _W_DOCS_3
    if num_docs >= 5:
        score += _W_DOCS_5

    if num_chunks >= 8:
        score += _W_CHUNKS_8
    if num_chunks >= 15:
        score += _W_CHUNKS_15

    if context_tokens >= 3000:
        score += _W_TOKENS_3K
    if context_tokens >= 6000:
        score += _W_TOKENS_6K

    score = min(score, 100.0)

    return ComplexitySignals(
        word_count=word_count,
        has_comparison=has_comparison,
        has_synthesis=has_synthesis,
        has_all_docs_signal=has_all_docs,
        has_risk_compliance=has_risk,
        has_multi_task=has_mt,
        num_distinct_documents=num_docs,
        num_chunks=num_chunks,
        context_tokens=context_tokens,
        score=score,
    )


def _score_to_tier(score: float) -> QueryTier:
    if score < _TIER_SIMPLE:
        return QueryTier.SIMPLE
    if score < _TIER_STANDARD:
        return QueryTier.STANDARD
    if score < _TIER_COMPLEX:
        return QueryTier.COMPLEX
    return QueryTier.REASONING
