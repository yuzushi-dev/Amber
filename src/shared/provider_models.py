from enum import Enum


class ProviderTier(str, Enum):
    """Cost tier for model routing."""

    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"
    LOCAL = "local"


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, message: str, provider: str, model: str | None = None):
        self.provider = provider
        self.model = model
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailableError(ProviderError):
    """Provider is unavailable (connection error, timeout, etc.)."""


class RateLimitError(ProviderError):
    """Rate limit exceeded, should retry after delay."""

    def __init__(
        self,
        message: str,
        provider: str,
        model: str | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message, provider, model)
        self.retry_after = retry_after


class QuotaExceededError(ProviderError):
    """Quota limit exceeded (insufficient funds/credits). Should NOT retry."""


class InvalidRequestError(ProviderError):
    """Invalid request parameters (bad input, context too long, etc.)."""


class AuthenticationError(ProviderError):
    """API key invalid or missing."""


class ConfigurationError(Exception):
    """
    Configuration is missing or invalid.

    Raised when required settings (e.g., provider/model) are not configured
    via admin UI or environment. This is a clear error with no silent fallbacks.
    """

    def __init__(self, setting_name: str, message: str | None = None):
        self.setting_name = setting_name
        default_msg = (
            f"Required setting '{setting_name}' is not configured. "
            "Please set it via /admin/settings or environment variables."
        )
        super().__init__(message or default_msg)
