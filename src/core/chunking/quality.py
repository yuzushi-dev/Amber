"""
Chunk Quality Scorer
===================

Evaluates text chunks for quality, primarily to detect and filter out
poor OCR results, scanner noise, and irrelevant fragments.

Ported from reference `ocr_processor.py`.
"""

import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class ChunkQualityScorer:
    """
    Heuristic scorer to assess text quality.
    """
    
    # Constants from reference implementation
    MIN_CHUNK_LENGTH = 50
    MIN_TEXT_RATIO = 0.5
    MAX_WHITESPACE_RATIO = 0.3
    MIN_WORDS_PER_LINE = 3.0
    
    def grade_chunk(self, text: str) -> Dict[str, Any]:
        """
        Assess the quality of a text chunk.

        Args:
            text: Text content to analyze

        Returns:
            Dictionary with quality assessment:
            - quality_score: float (0.0 - 1.0)
            - is_readable: bool
            - reason: str
            - metrics: dict
        """
        if not text or len(text.strip()) < 5:
            return {
                "quality_score": 0.0,
                "is_readable": False,
                "reason": "Empty or too short",
                "metrics": {"total_chars": len(text) if text else 0}
            }

        # 1. Calculate base metrics
        total_chars = len(text)
        alpha_chars = sum(1 for c in text if c.isalnum())
        whitespace_chars = sum(1 for c in text if c.isspace())
        lines = text.split("\n")
        
        # Composition ratios
        text_ratio = alpha_chars / total_chars if total_chars > 0 else 0
        whitespace_ratio = whitespace_chars / total_chars if total_chars > 0 else 0
        
        # Link structure
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        avg_words_per_line = 0
        if non_empty_lines:
            total_words = sum(len(line.split()) for line in non_empty_lines)
            avg_words_per_line = total_words / len(non_empty_lines)
            
        # 2. Pattern Detection
        # Non-ASCII detection (common in bad OCR)
        has_ocr_artifacts = bool(re.search(r"[^\x00-\x7F]+", text))
        
        # Fragmented words (e.g. "t h i s i s") - definition: 1-2 char words > 10%
        short_words = len(re.findall(r"\b\w{1,2}\b", text))
        has_fragmented_words = (short_words > total_chars * 0.1)
        
        # Excessive spacing
        has_excessive_spaces = "   " in text
        
        # 3. Calculate Score
        # Weights: Text Ratio (40%), Whitespace (30%), Sentence Structure (30%)
        # avg_words_per_line normalized: 5 words/line is considered "good" (1.0)
        
        score = (
            text_ratio * 0.4
            + (1 - whitespace_ratio) * 0.3
            + min(avg_words_per_line / 5, 1.0) * 0.3
        )
        
        # 4. Apply Penalties
        if has_ocr_artifacts:
            score *= 0.8
        if has_fragmented_words:
            score *= 0.7
        if has_excessive_spaces:
            score *= 0.9
        if total_chars < self.MIN_CHUNK_LENGTH:
            score *= 0.6
            
        # Clamp score
        score = max(0.0, min(1.0, score))
        
        # 5. Determine Readability
        # Strict thresholds for "readable"
        is_readable = (
            score >= 0.5
            and text_ratio >= self.MIN_TEXT_RATIO
            and whitespace_ratio <= self.MAX_WHITESPACE_RATIO
            and avg_words_per_line >= self.MIN_WORDS_PER_LINE
            and not (has_fragmented_words and has_ocr_artifacts)
        )
        
        # 6. Generate Reason
        reasons = []
        if text_ratio < self.MIN_TEXT_RATIO:
            reasons.append(f"Low text ratio ({text_ratio:.2f})")
        if whitespace_ratio > self.MAX_WHITESPACE_RATIO:
            reasons.append(f"High whitespace ({whitespace_ratio:.2f})")
        if avg_words_per_line < self.MIN_WORDS_PER_LINE:
            reasons.append(f"Choppy lines ({avg_words_per_line:.1f} w/l)")
        if has_fragmented_words:
            reasons.append("Fragmented text")
        if has_ocr_artifacts:
            reasons.append("OCR Artifacts")
        if total_chars < self.MIN_CHUNK_LENGTH:
            reasons.append("Too short")
            
        reason_str = "; ".join(reasons) if reasons else "Good quality"
        
        return {
            "quality_score": round(score, 2),
            "is_readable": is_readable,
            "reason": reason_str,
            "metrics": {
                "total_chars": total_chars,
                "text_ratio": round(text_ratio, 2),
                "whitespace_ratio": round(whitespace_ratio, 2),
                "avg_words_per_line": round(avg_words_per_line, 1),
                "has_artifacts": has_ocr_artifacts,
                "is_fragmented": has_fragmented_words
            }
        }
