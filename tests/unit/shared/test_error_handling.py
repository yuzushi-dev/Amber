
import pytest
from src.shared.error_handling import map_exception_to_error_data
from src.core.generation.domain.provider_models import (
    ProviderError,
    QuotaExceededError,
    RateLimitError,
)

def test_map_quota_exceeded_error():
    err = QuotaExceededError("Quota limit reached", provider="openai")
    result = map_exception_to_error_data(err)
    
    assert result["code"] == "quota_exceeded"
    assert result["provider"] == "Openai"
    assert "insufficient quota" in result["message"].lower() or "billing" in result["message"].lower()

def test_map_rate_limit_error():
    err = RateLimitError("Rate limit exceeded", provider="anthropic")
    result = map_exception_to_error_data(err)
    
    assert result["code"] == "rate_limit"
    assert result["provider"] == "Anthropic"
    assert "rate limit" in result["message"].lower() or "slow down" in result["message"].lower()

def test_map_generic_provider_error():
    err = ProviderError("Service down", provider="cohere")
    result = map_exception_to_error_data(err)
    
    assert result["code"] == "processing_error" # Default fallback for generic provider error unless mapped
    assert result["provider"] == "Cohere"

def test_map_unknown_error():
    err = ValueError("Something confusing")
    result = map_exception_to_error_data(err)
    
    assert result["code"] == "processing_error"
    assert result["provider"] == "System"
