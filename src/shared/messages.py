"""
Shared User Messages
====================

Centralized repository for user-facing messages, particularly for errors 
and status updates used across LLM endpoints.
"""

ERROR_MESSAGES = {
    # Quota & Rate Limits
    "quota_exceeded": "Quota exceeded. Please check your billing/credits.",
    "rate_limit": "Rate limit exceeded during retrieval. Please slow down.",
    
    # Generic
    "default": "An unexpected error occurred.",
    "service_unavailable": "Service temporarily unavailable. Please try again later.",
    "context_length": "Input too long. Please reduce the size of your request.",
}
