from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProviderTier(str, Enum):
    """Cost tier for model routing."""

    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"
    LOCAL = "local"


class ProviderType(str, Enum):
    """Type of provider."""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"


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


@dataclass
class TokenUsage:
    """Token usage statistics."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class GenerationResult:
    """Result from LLM generation."""

    text: str
    model: str
    provider: str
    usage: TokenUsage
    finish_reason: str | None = None
    latency_ms: float = 0.0
    cost_estimate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EmbeddingResult:
    """Result from embedding generation."""

    embeddings: list[list[float]]
    model: str
    provider: str
    usage: TokenUsage
    dimensions: int = 0
    latency_ms: float = 0.0
    cost_estimate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RerankResult:
    """Result from reranking."""

    @dataclass
    class ScoredItem:
        index: int
        score: float
        text: str | None = None

    results: list[ScoredItem]
    model: str
    provider: str
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderConfig:
    """Configuration for a provider."""

    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    max_retries: int = 3
    usage_tracker: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
