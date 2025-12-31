import pytest
from src.core.utils.tokenizer import Tokenizer

def test_count_tokens():
    text = "Hello, world!"
    # Basic check, exact count depends on tiktoken version/model
    count = Tokenizer.count_tokens(text)
    assert count > 0
    
    # Empty string
    assert Tokenizer.count_tokens("") == 0
    assert Tokenizer.count_tokens(None) == 0

def test_truncate_to_budget():
    text = "This is a longer sentence that we want to truncate."
    # Truncate to very few tokens
    # If tiktoken is mocked, 5 tokens -> 20 chars
    truncated = Tokenizer.truncate_to_budget(text, 5)
    assert len(truncated) < len(text)
    # The token count might be exact or fallback estimate
    count = Tokenizer.count_tokens(truncated)
    assert count <= 8 # Allow some buffer for fallback estimation

def test_model_specific_encoding():
    text = "Special tokens and model specific behavior."
    count_mini = Tokenizer.count_tokens(text, model="gpt-4o-mini")
    count_legacy = Tokenizer.count_tokens(text, model="gpt-3.5-turbo")
    # Just ensure it doesn't crash and returns valid counts
    assert count_mini > 0
    assert count_legacy > 0
