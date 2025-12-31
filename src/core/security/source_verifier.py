from typing import List, Dict, Optional
import re

class SourceVerifier:
    """
    Security component to verify that generated answers are grounded in the source text.
    Ensures citations actually exist in the retrieved documents.
    """

    def verify_citation(self, citation_text: str, source_text: str) -> bool:
        """
        Verifies if the citation text exists within the source text.
        Uses fuzzy matching or normalization to handle minor variations.
        """
        if not citation_text or not source_text:
            return False
            
        # 1. Exact match
        if citation_text in source_text:
            return True
            
        # 2. Normalized match (ignore whitespace/case)
        norm_citation = re.sub(r'\s+', ' ', citation_text).strip().lower()
        norm_source = re.sub(r'\s+', ' ', source_text).strip().lower()
        
        if norm_citation in norm_source:
            return True
            
        # 3. Fuzzy match (optional, skipping for MVP strictness)
        # We want STRICT grounding for security/trust.
        
        return False

    def verify_answer_grounding(self, answer: str, context_chunks: List[str]) -> bool:
        """
        Checks if the answer implies citations that are supported by context.
        Note: This is hard without parsing the answer's citation format.
        Assuming answer contains [Source ID] or quoted text.
        
        For MVP, we might rely on the LLM to output specific citation format like <cite>text</cite>
        or check if quoted substrings > N chars exist in context.
        """
        # Placeholder for more advanced logic.
        # For Phase 11 MVP, we provide the verification logic to be called by the Generator.
        return True
