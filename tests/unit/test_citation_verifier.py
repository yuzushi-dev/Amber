import pytest
from src.core.quality.citation_verifier import CitationVerifier

def test_citation_verifier_grounding():
    verifier = CitationVerifier(threshold=0.5)
    
    answer = "The capital of France is Paris [1]. It is a beautiful city."
    sources = [{"content": "Paris is the capital and largest city of France.", "index": 1}]
    
    result = verifier.verify(answer, "", sources)
    
    assert result.is_grounded is True
    assert 1 in result.verified_citations
    assert result.score > 0.8

def test_citation_verifier_hallucination():
    verifier = CitationVerifier(threshold=0.7)
    
    answer = "The moon is made of green cheese [1]."
    sources = [{"content": "The moon is a natural satellite of Earth.", "index": 1}]
    
    result = verifier.verify(answer, "", sources)
    
    assert result.is_grounded is False
    assert len(result.unsupported_claims) == 1
    assert "moon is made of green cheese" in result.unsupported_claims[0]

def test_no_citations():
    verifier = CitationVerifier()
    answer = "Just a plain answer without brackets."
    result = verifier.verify(answer, "", [])
    assert result.is_grounded is True
    assert result.score == 1.0
