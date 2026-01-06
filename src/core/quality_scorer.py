"""
Quality Scorer for evaluating answer and extraction quality.
Implements hybrid scoring (LLM + Heuristics).
"""

import logging
import json
import re
from typing import List, Dict, Any, Optional

from src.core.providers.factory import get_llm_provider
from src.core.providers.base import ProviderTier

logger = logging.getLogger(__name__)

class QualityScorer:
    """Scorer using hybrid metrics (LLM + Heuristics)."""
    
    def __init__(self):
        self.weights = {
            "context_relevance": 0.3,
            "answer_completeness": 0.3,
            "factual_grounding": 0.3, 
            "coherence": 0.1
        }
        
    async def calculate_quality_score(
        self,
        answer: str,
        query: str,
        context_chunks: List[Dict[str, Any]] = None,
        sources: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive quality score.
        """
        try:
            # 1. Try single LLM call for all scores
            scores = await self._score_with_single_llm(answer, query, context_chunks, sources)
            
            if not scores:
                scores = {}
                # Fallbacks
                scores["context_relevance"] = self._heuristic_context_relevance(answer, context_chunks)
                scores["answer_completeness"] = self._heuristic_completeness(answer, query)
                scores["factual_grounding"] = 50.0 # Default if LLM fails
                scores["coherence"] = self._heuristic_coherence(answer)
            
            # Additional heuristic check for checking citation quality if sources exist
            scores["citation_quality"] = self._score_citation_quality(answer, sources)
                
            # Weighted Total
            total_score = sum(
                scores.get(comp, 0) * self.weights.get(comp, 0) 
                for comp in self.weights
            )
            
            # Add citation bonus if applicable (small weight implicit)
            # Normalizing to 100 max just in case
            total_score = min(total_score, 100.0)
            
            confidence = self._calculate_confidence(list(scores.values()))
            
            return {
                "total": round(total_score, 1),
                "breakdown": {k: round(v, 1) for k, v in scores.items()},
                "confidence": confidence
            }
            
        except Exception as e:
            logger.error(f"Quality calculation failed: {e}")
            return {"total": 0.0, "error": str(e)}

    async def _score_with_single_llm(self, answer, query, context_chunks, sources):
        try:
            chunks_text = "\n".join([c.get("content","")[:500] for c in (context_chunks or [])[:5]])
            prompt = f"""Evaluate answer quality on 0-10 scale. Return ONLY JSON.
Keys: context_relevance, answer_completeness, factual_grounding, coherence.

Query: {query}
Answer: {answer}
Context: {chunks_text}

JSON:"""
            # Use Factory to get provider
            provider = get_llm_provider(tier=ProviderTier.ECONOMY)
            response = await provider.generate(prompt=prompt, temperature=0.0)
            text = response.text
            
            # Simple parsing logic
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                # Normalize 0-10 to 0-100
                return {k: float(v)*10 for k,v in data.items() if k in self.weights}
                
        except Exception as e:
            logger.debug(f"LLM scoring failed: {e}")
            return None

    def _heuristic_context_relevance(self, answer, context_chunks):
        if not context_chunks: return 50.0
        # Simple Jaccard-ish overlap
        ans_words = set(answer.lower().split())
        ctx_words = set(" ".join([c.get("content","") for c in context_chunks]).lower().split())
        overlap = len(ans_words & ctx_words)
        return min((overlap / len(ans_words)) * 100 * 1.5, 100) if ans_words else 0

    def _heuristic_completeness(self, answer, query):
        q_words = set(query.lower().split())
        a_words = set(answer.lower().split())
        coverage = len(q_words & a_words) / len(q_words) if q_words else 0
        length_score = min(len(answer) / 200, 1.0) 
        return (coverage * 0.7 + length_score * 0.3) * 100

    def _heuristic_coherence(self, answer):
        # Basic placeholder: check sentence structure/length
        if len(answer) < 10: return 10.0
        return 80.0 # Bias towards assumption of coherence if length is okay

    def _score_citation_quality(self, answer, sources):
        if not sources: return 50.0
        # Check if [1], [2] etc matches sources
        count = sum(1 for i in range(len(sources)) if f"[{i+1}]" in answer)
        ratio = count / len(sources)
        return ratio * 100

    def _calculate_confidence(self, scores):
        if not scores: return "low"
        avg = sum(scores)/len(scores)
        variance = sum((s - avg)**2 for s in scores) / len(scores)
        if variance < 100: return "high"
        if variance < 400: return "medium"
        return "low"

quality_scorer = QualityScorer()
