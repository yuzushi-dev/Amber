"""
Tests for citation normalization in GenerationService.

These tests verify that the citation regex correctly normalizes
various LLM output formats into the standard [[Source:N]] format.
"""

import pytest
import re

# Import the pattern directly to test in isolation
CITATION_NORMALIZE_PATTERN = re.compile(
    r"\[\[\s*(?:source(?:\s*:\s*id|\s*id|id)?\s*[: ]\s*)?(\d+)\s*\]\]",
    re.IGNORECASE,
)


def normalize_citations(text: str) -> str:
    """Mirror of the _normalize_citations method."""
    if not text:
        return text
    return CITATION_NORMALIZE_PATTERN.sub(r"[[Source:\1]]", text)


class TestCitationNormalization:
    """Test suite for citation regex patterns."""

    # === Standard formats (should all normalize to [[Source:N]]) ===
    
    def test_standard_source_format(self):
        """[[Source:3]] -> [[Source:3]]"""
        result = normalize_citations("According to [[Source:3]], this is true.")
        assert "[[Source:3]]" in result

    def test_lowercase_source(self):
        """[[source:3]] -> [[Source:3]]"""
        result = normalize_citations("According to [[source:3]], this is true.")
        assert "[[Source:3]]" in result

    def test_source_with_space(self):
        """[[Source 3]] -> [[Source:3]]"""
        result = normalize_citations("According to [[Source 3]], this is true.")
        assert "[[Source:3]]" in result

    def test_source_with_colon_space(self):
        """[[Source: 3]] -> [[Source:3]]"""
        result = normalize_citations("According to [[Source: 3]], this is true.")
        assert "[[Source:3]]" in result

    def test_source_id_format(self):
        """[[Source ID:3]] -> [[Source:3]]"""
        result = normalize_citations("According to [[Source ID:3]], this is true.")
        assert "[[Source:3]]" in result

    def test_source_colon_id_format(self):
        """[[Source:ID:3]] -> [[Source:3]]"""
        result = normalize_citations("According to [[Source:ID:3]], this is true.")
        assert "[[Source:3]]" in result

    def test_whitespace_variations(self):
        """[[ Source : 3 ]] -> [[Source:3]]"""
        result = normalize_citations("According to [[ Source : 3 ]], this is true.")
        assert "[[Source:3]]" in result

    # === NEW: Bare number format ===
    
    def test_bare_number_double_brackets(self):
        """[[3]] -> [[Source:3]] (critical for LLM resilience)"""
        result = normalize_citations("According to [[3]], this is true.")
        assert "[[Source:3]]" in result

    def test_bare_number_with_whitespace(self):
        """[[ 3 ]] -> [[Source:3]]"""
        result = normalize_citations("According to [[ 3 ]], this is true.")
        assert "[[Source:3]]" in result

    # === Multiple citations ===
    
    def test_multiple_citations(self):
        """Multiple citations in one string"""
        text = "According to [[Source:1]] and [[2]], the answer is based on [[source 3]]."
        result = normalize_citations(text)
        assert "[[Source:1]]" in result
        assert "[[Source:2]]" in result
        assert "[[Source:3]]" in result

    def test_mixed_formats(self):
        """Mix of different formats in one text"""
        text = "See [[Source:1]], [[2]], [[source ID:3]], and [[ 4 ]]."
        result = normalize_citations(text)
        assert "[[Source:1]]" in result
        assert "[[Source:2]]" in result
        assert "[[Source:3]]" in result
        assert "[[Source:4]]" in result

    # === Edge cases ===
    
    def test_empty_string(self):
        """Empty string should return empty"""
        assert normalize_citations("") == ""

    def test_none_input(self):
        """None should return None"""
        assert normalize_citations(None) is None

    def test_no_citations(self):
        """Text without citations remains unchanged"""
        text = "This is a simple answer without any citations."
        assert normalize_citations(text) == text

    def test_single_bracket_not_matched(self):
        """[3] should NOT be normalized (single brackets, different format)"""
        text = "According to [3], this is true."
        result = normalize_citations(text)
        # Should remain unchanged since it's not [[N]]
        assert result == text

    def test_preserves_surrounding_text(self):
        """Normalization should not affect surrounding text"""
        text = "Start [[1]] middle [[source:2]] end."
        result = normalize_citations(text)
        assert result == "Start [[Source:1]] middle [[Source:2]] end."

    def test_two_digit_numbers(self):
        """Two-digit source numbers"""
        result = normalize_citations("See [[Source:10]] and [[15]].")
        assert "[[Source:10]]" in result
        assert "[[Source:15]]" in result

    def test_three_digit_numbers(self):
        """Three-digit source numbers (edge case)"""
        result = normalize_citations("References [[100]] and [[Source:999]].")
        assert "[[Source:100]]" in result
        assert "[[Source:999]]" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
