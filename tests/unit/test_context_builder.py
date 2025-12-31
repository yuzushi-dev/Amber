import pytest
from src.core.generation.context_builder import ContextBuilder

def test_context_builder_budget():
    candidates = [
        {"content": "First chunk content.", "chunk_id": "1"},
        {"content": "Second chunk content that is a bit longer.", "chunk_id": "2"},
        {"content": "Third chunk content.", "chunk_id": "3"},
    ]
    
    # Very small budget
    builder = ContextBuilder(max_tokens=20)
    result = builder.build(candidates)
    
    assert len(result.used_candidates) < 3
    assert result.tokens <= 20
    assert "First chunk" in result.content

def test_sentence_truncation():
    text = "This is sentence one. This is sentence two! And sentence three?"
    builder = ContextBuilder(max_tokens=60) # Should fit about 1-2 sentences
    
    # Mocking a candidate with long text
    candidates = [{"content": text * 10, "chunk_id": "long"}]
    result = builder.build(candidates)
    
    # Check that it ends with punctuation
    assert result.content.strip()[-1] in ".!?"
    assert result.tokens <= 60

def test_metadata_inclusion():
    candidates = [{"content": "Content", "title": "Secret Document"}]
    builder = ContextBuilder()
    result = builder.build(candidates)
    
    assert "Source ID: 1" in result.content
    assert "Title: Secret Document" in result.content
