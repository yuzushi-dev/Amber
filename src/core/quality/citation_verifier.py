"""
Citation Verifier
=================

Ensures that LLM-generated answers are grounded in the provided sources.
"""

import logging
import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

from src.core.utils.tokenizer import Tokenizer

logger = logging.getLogger(__name__)

@dataclass
class GroundingResult:
    """Result of grounding verification."""
    is_grounded: bool
    score: float
    unsupported_claims: List[str]
    verified_citations: List[int]

class CitationVerifier:
    """
    Verifies that claims in an answer are supported by cited sources.
    """

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def verify(self, answer: str, context: str, sources: List[Any]) -> GroundingResult:
        """
        Verify grounding of an answer against sources.
        
        Args:
            answer: The generated answer text.
            context: The full context string provided to the model.
            sources: List of Source objects or candidate dicts.
            
        Returns:
            GroundingResult with status and findings.
        """
        # 1. Extract citations and the sentences they anchor to
        claims = self._extract_claims(answer)
        
        if not claims:
            # If no citations, we can't verify grounding this way.
            # In production, we might want to flag this.
            return GroundingResult(True, 1.0, [], [])

        verified_citations = []
        unsupported_claims = []
        scores = []

        # 2. Check each claim
        for sentence, citation_indices in claims:
            sentence_is_grounded = False
            
            for idx in citation_indices:
                # Find the source content
                source_content = self._get_source_content(idx, sources)
                if not source_content:
                    continue
                
                # Simple keyword overlap / fuzzy check for grounding
                # In Phase 7 "Heavy" mode, this would use an NLI model.
                score = self._compute_alignment_score(sentence, source_content)
                scores.append(score)
                
                if score >= self.threshold:
                    sentence_is_grounded = True
                    verified_citations.append(idx)
            
            if not sentence_is_grounded:
                unsupported_claims.append(sentence)

        grounding_score = sum(scores) / len(scores) if scores else 1.0
        is_grounded = len(unsupported_claims) == 0

        return GroundingResult(
            is_grounded=is_grounded,
            score=round(grounding_score, 2),
            unsupported_claims=unsupported_claims,
            verified_citations=list(set(verified_citations))
        )

    def _extract_claims(self, text: str) -> List[Tuple[str, List[int]]]:
        """Splits answer into sentences and extracts associated citations."""
        # Split by sentence boundaries roughly
        sentences = re.split(r'(?<=[.!?])\s+', text)
        claims = []
        
        for sentence in sentences:
            citations = [int(m) for m in re.findall(r'\[(\d+)\]', sentence)]
            if citations:
                # Clean sentence from citation tags for alignment check
                clean_sentence = re.sub(r'\[\d+\]', '', sentence).strip()
                claims.append((clean_sentence, citations))
        
        return claims

    def _get_source_content(self, index: int, sources: List[Any]) -> str:
        """Retrieves source content for a given 1-based index."""
        for s in sources:
            # Check for Source object
            if hasattr(s, 'index') and s.index == index:
                # We need the full content, not just preview
                # In Phase 7, we might need to pass candidates separately or enrich Source
                return getattr(s, 'content', '') 
            # Check for dict (candidate)
            elif isinstance(s, dict) and s.get('index') == index:
                 return s.get('content', '')
        return ""

    def _compute_alignment_score(self, sentence: str, source: str) -> float:
        """Computes a simple alignment score between sentence and source."""
        if not sentence or not source:
            return 0.0
            
        # Basic keyword overlap (normalized)
        s_words = set(re.findall(r'\w+', sentence.lower()))
        ctx_words = set(re.findall(r'\w+', source.lower()))
        
        if not s_words:
            return 1.0
            
        overlap = s_words.intersection(ctx_words)
        # We value common words less
        stop_words = {'the', 'a', 'an', 'in', 'on', 'at', 'is', 'are', 'was', 'were', 'to', 'for', 'of', 'and', 'or'}
        significant_words = s_words - stop_words
        
        if not significant_words:
             return len(overlap) / len(s_words)
             
        score = len(significant_words.intersection(ctx_words)) / len(significant_words)
        return score
