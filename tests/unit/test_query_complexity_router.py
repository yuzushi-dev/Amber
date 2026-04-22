"""
Tests for ZTD-1819: QueryComplexityRouter.

Ground truth derived from the Manifest evaluation (10 queries tested against
the live router; expected tiers reflect what a well-calibrated router should
return for Amber's Italian-language RAG workload).

Each test passes explicit context signals (candidates, context_tokens) so
the scoring is deterministic and independent of real retrieval.
"""

import pytest

from src.core.generation.application.intelligence.query_complexity import (
    QueryComplexityRouter,
    QueryTier,
)


def _make_candidates(num_docs: int, num_chunks: int) -> list[dict]:
    """Produce synthetic candidates with distinct document IDs."""
    candidates = []
    for i in range(num_chunks):
        doc_id = f"doc_{i % num_docs}"
        candidates.append(
            {
                "chunk_id": f"chunk_{i}",
                "document_id": doc_id,
                "content": "Lorem ipsum dolor sit amet.",
                "metadata": {"document_id": doc_id},
            }
        )
    return candidates


router = QueryComplexityRouter()


# ---------------------------------------------------------------------------
# SIMPLE tier
# ---------------------------------------------------------------------------


def test_faq_single_doc_is_simple():
    """Pure FAQ, 1 document, small context → SIMPLE."""
    candidates = _make_candidates(num_docs=1, num_chunks=3)
    tier = router.classify(
        query="Qual è la policy per le ferie aziendali?",
        candidates=candidates,
        context_tokens=500,
    )
    assert tier == QueryTier.SIMPLE


def test_definition_lookup_is_simple():
    """Definition question, 1 document → SIMPLE."""
    candidates = _make_candidates(num_docs=1, num_chunks=2)
    tier = router.classify(
        query="Cos'è un contratto a tempo indeterminato?",
        candidates=candidates,
        context_tokens=300,
    )
    assert tier == QueryTier.SIMPLE


def test_contact_lookup_is_simple():
    """Single-fact lookup → SIMPLE regardless of context."""
    candidates = _make_candidates(num_docs=1, num_chunks=2)
    tier = router.classify(
        query="Qual è il numero di telefono dell'ufficio HR?",
        candidates=candidates,
        context_tokens=200,
    )
    assert tier == QueryTier.SIMPLE


# ---------------------------------------------------------------------------
# STANDARD tier
# ---------------------------------------------------------------------------


def test_two_concept_comparison_is_standard():
    """Lightweight comparison between 2 concepts, 2 docs → STANDARD."""
    candidates = _make_candidates(num_docs=2, num_chunks=5)
    tier = router.classify(
        query="Spiega le differenze tra contratto a termine e contratto a progetto.",
        candidates=candidates,
        context_tokens=1800,
    )
    assert tier == QueryTier.STANDARD


def test_procedural_multi_doc_is_standard():
    """Procedural query with 2 docs and moderate context → STANDARD.

    A reimbursement-requirements question typically retrieves 8+ chunks from
    the HR policy and expense regulations — enough context to reach STANDARD.
    """
    candidates = _make_candidates(num_docs=2, num_chunks=8)
    tier = router.classify(
        query="Quali sono i requisiti per richiedere il rimborso spese trasferta?",
        candidates=candidates,
        context_tokens=3000,
    )
    assert tier == QueryTier.STANDARD


# ---------------------------------------------------------------------------
# COMPLEX tier
# ---------------------------------------------------------------------------


def test_multidoc_compare_is_complex():
    """Explicit multi-document comparison, 3 docs, medium context → COMPLEX."""
    candidates = _make_candidates(num_docs=3, num_chunks=10)
    tier = router.classify(
        query=(
            "Confronta le clausole di riservatezza nei tre contratti di fornitura "
            "caricati e identifica le differenze principali."
        ),
        candidates=candidates,
        context_tokens=4000,
    )
    assert tier == QueryTier.COMPLEX


def test_audit_table_across_docs_is_complex():
    """Creating a comparison table across multiple contracts → COMPLEX."""
    candidates = _make_candidates(num_docs=4, num_chunks=12)
    tier = router.classify(
        query=(
            "Esamina tutti i contratti caricati e crea una tabella comparativa "
            "delle penali previste per inadempimento."
        ),
        candidates=candidates,
        context_tokens=5000,
    )
    assert tier == QueryTier.COMPLEX


# ---------------------------------------------------------------------------
# REASONING tier
# ---------------------------------------------------------------------------


def test_legal_risk_strategy_is_reasoning():
    """Strategic risk identification + mitigation plan across all docs → REASONING."""
    candidates = _make_candidates(num_docs=5, num_chunks=16)
    tier = router.classify(
        query=(
            "Sulla base di tutti i contratti e documenti legali disponibili, "
            "identifica le aree di rischio legale più critiche e proponi una "
            "strategia di mitigazione prioritizzata."
        ),
        candidates=candidates,
        context_tokens=7000,
    )
    assert tier == QueryTier.REASONING


def test_cross_domain_compliance_plan_is_reasoning():
    """Cross-domain synthesis + timeline + ownership → REASONING."""
    candidates = _make_candidates(num_docs=5, num_chunks=16)
    tier = router.classify(
        query=(
            "Analizza le interdipendenze tra le policy aziendali, i contratti di "
            "fornitura e i requisiti normativi, e sviluppa un piano di conformità "
            "integrato con timeline e responsabilità."
        ),
        candidates=candidates,
        context_tokens=7000,
    )
    assert tier == QueryTier.REASONING


# ---------------------------------------------------------------------------
# English language parity
# ---------------------------------------------------------------------------


def test_english_simple_is_simple():
    candidates = _make_candidates(num_docs=1, num_chunks=2)
    tier = router.classify(
        query="What is the vacation policy?",
        candidates=candidates,
        context_tokens=300,
    )
    assert tier == QueryTier.SIMPLE


def test_english_complex_compare_is_complex():
    """English cross-document comparison → COMPLEX."""
    candidates = _make_candidates(num_docs=3, num_chunks=10)
    tier = router.classify(
        query=(
            "Compare the confidentiality clauses across all three supplier contracts "
            "and identify the key differences."
        ),
        candidates=candidates,
        context_tokens=4000,
    )
    assert tier == QueryTier.COMPLEX


def test_english_reasoning_is_reasoning():
    """English strategic multi-doc synthesis → REASONING."""
    candidates = _make_candidates(num_docs=5, num_chunks=16)
    tier = router.classify(
        query=(
            "Based on all uploaded legal documents, identify the critical legal risk "
            "areas, analyze their interdependencies, and develop a prioritized "
            "compliance strategy with timeline and ownership."
        ),
        candidates=candidates,
        context_tokens=7000,
    )
    assert tier == QueryTier.REASONING


# ---------------------------------------------------------------------------
# RAG context signals dominate when query is ambiguous
# ---------------------------------------------------------------------------


def test_many_docs_escalates_tier():
    """Even a short query escalates to COMPLEX when 5+ distinct docs are retrieved."""
    candidates = _make_candidates(num_docs=5, num_chunks=15)
    tier = router.classify(
        query="Dimmi tutto quello che c'è scritto.",
        candidates=candidates,
        context_tokens=6500,
    )
    assert tier in (QueryTier.COMPLEX, QueryTier.REASONING)


def test_single_doc_caps_at_standard():
    """A synthesis-sounding query with only 1 document never exceeds STANDARD."""
    candidates = _make_candidates(num_docs=1, num_chunks=4)
    tier = router.classify(
        query="Sviluppa una strategia basata su questi documenti.",
        candidates=candidates,
        context_tokens=1200,
    )
    assert tier in (QueryTier.SIMPLE, QueryTier.STANDARD)


# ---------------------------------------------------------------------------
# Multi-task dimension
# ---------------------------------------------------------------------------


def test_multi_task_query_escalates_tier():
    """A query with 3+ sub-tasks (e.g. 'configure X for: A, B, C') scores higher."""
    # Without multi-task signal this would be STANDARD with 2 docs.
    # With multi-task (+15) it must reach COMPLEX.
    candidates = _make_candidates(num_docs=2, num_chunks=8)
    tier = router.classify(
        query=(
            "I am running Microsoft Active Directory, list the steps to configure "
            "Carbonio to use AD for: autoprovisioning, authentication, external GAL"
        ),
        candidates=candidates,
        context_tokens=3000,
    )
    assert tier == QueryTier.COMPLEX


def test_multi_task_detected_in_signals():
    """has_multi_task is True when 3+ comma-separated sub-tasks are present."""
    from src.core.generation.application.intelligence.query_complexity import ComplexitySignals

    candidates = _make_candidates(num_docs=1, num_chunks=3)
    tier, signals = router.classify_with_signals(
        query="Configure the system for: autoprovisioning, authentication, external GAL",
        candidates=candidates,
        context_tokens=500,
    )
    assert signals.has_multi_task is True


def test_single_task_no_multi_task_signal():
    """A straightforward single-task query must NOT trigger has_multi_task."""
    from src.core.generation.application.intelligence.query_complexity import ComplexitySignals

    candidates = _make_candidates(num_docs=1, num_chunks=3)
    _, signals = router.classify_with_signals(
        query="How to install Carbonio CE on Ubuntu 24?",
        candidates=candidates,
        context_tokens=500,
    )
    assert signals.has_multi_task is False


# ---------------------------------------------------------------------------
# Signals API
# ---------------------------------------------------------------------------


def test_signals_are_returned():
    """classify_with_signals exposes the raw score and dimension breakdown."""
    from src.core.generation.application.intelligence.query_complexity import ComplexitySignals

    candidates = _make_candidates(num_docs=3, num_chunks=10)
    tier, signals = router.classify_with_signals(
        query="Confronta le clausole di riservatezza nei tre contratti.",
        candidates=candidates,
        context_tokens=4000,
    )
    assert isinstance(signals, ComplexitySignals)
    assert 0 <= signals.score <= 100
    assert signals.num_distinct_documents == 3
    assert signals.has_comparison is True
    assert hasattr(signals, "has_multi_task")
