from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.shared.provider_models import (
    AuthenticationError,
    ConfigurationError,
    InvalidRequestError,
    ProviderError,
    ProviderTier,
    ProviderUnavailableError,
    QuotaExceededError,
    RateLimitError,
)

__all__ = [
    "ProviderTier",
    "ProviderType",
    "ProviderError",
    "ProviderUnavailableError",
    "RateLimitError",
    "QuotaExceededError",
    "InvalidRequestError",
    "AuthenticationError",
    "ConfigurationError",
    "TokenUsage",
    "GenerationResult",
    "EmbeddingResult",
    "RerankResult",
    "ProviderConfig",
]


class ProviderType(str, Enum):
    """Type of provider."""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"


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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


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
