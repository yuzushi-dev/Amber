"""
Shared Error Handling
=====================

Utilities for consistent exception mapping across the application.
"""
import logging
from typing import Any

from src.shared.messages import ERROR_MESSAGES
from src.core.generation.domain.provider_models import (
    ProviderError,
    QuotaExceededError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

def map_exception_to_error_data(e: Exception) -> dict[str, Any]:
    """
    Map an exception to a structured error data dictionary.
    
    Handles:
    - QuotaExceededError
    - RateLimitError
    - Tenacity RetryError (unwrapping)
    
    Returns:
        dict: {
            "code": str,       # Error code (e.g., 'quota_exceeded', 'rate_limit')
            "message": str,    # User-friendly message
            "provider": str,   # Provider name if available
            "details": str,    # Raw exception string (optional/debug)
        }
    """
    error_code = "processing_error"
    provider = "System"
    message = ERROR_MESSAGES.get("default", "An unexpected error occurred.")
    
    # Unwrap Tenacity RetryError
    try:
        import tenacity
        if isinstance(e, tenacity.RetryError):
            if e.last_attempt:
                inner_exc = e.last_attempt.exception()
                if inner_exc:
                    e = inner_exc
    except ImportError:
        pass

    # Check for known errors
    if isinstance(e, QuotaExceededError) or "QuotaExceededError" in type(e).__name__ or "insufficient_quota" in str(e):
        error_code = "quota_exceeded"
        message = ERROR_MESSAGES.get("quota_exceeded", message)
        provider = "Embedding Provider"
        if hasattr(e, "provider"):
            provider = e.provider.title()

    elif isinstance(e, RateLimitError) or "RateLimitError" in type(e).__name__ or "429" in str(e):
        error_code = "rate_limit"
        message = ERROR_MESSAGES.get("rate_limit", message)
        provider = "Embedding Provider" 
        if hasattr(e, "provider"):
            provider = e.provider.title()

    # Generic Fallback with safe message extraction
    else:
        # If it's a known provider error but generic
        if isinstance(e, ProviderError):
             message = ERROR_MESSAGES.get("service_unavailable", message)
             if hasattr(e, "provider"):
                 provider = e.provider.title()

    return {
        "code": error_code,
        "message": message,
        "provider": provider,
        "details": str(e)
    }
