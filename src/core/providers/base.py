"""
Provider Base Classes
=====================

Abstract base classes for LLM, Embedding, and Reranker providers.
All providers implement these interfaces for consistent usage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from src.core.observability.tracer import trace_span


class ProviderTier(str, Enum):
    """Cost tier for model routing."""

    ECONOMY = "economy"  # <$1/1M tokens (gpt-4o-mini, haiku, deepseek-v3)
    STANDARD = "standard"  # $3-15/1M tokens (gpt-4o, sonnet)
    PREMIUM = "premium"  # $15-75/1M tokens (opus, o1)
    LOCAL = "local"  # Self-hosted, no cost


class ProviderType(str, Enum):
    """Type of provider."""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"


# =============================================================================
# Exceptions
# =============================================================================


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, message: str, provider: str, model: str | None = None):
        self.provider = provider
        self.model = model
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailableError(ProviderError):
    """Provider is unavailable (connection error, timeout, etc.)."""

    pass


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


class InvalidRequestError(ProviderError):
    """Invalid request parameters (bad input, context too long, etc.)."""

    pass


class AuthenticationError(ProviderError):
    """API key invalid or missing."""

    pass


# =============================================================================
# Result Types
# =============================================================================


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


# =============================================================================
# Base Provider Classes
# =============================================================================


@dataclass
class ProviderConfig:
    """Configuration for a provider."""

    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    max_retries: int = 3
    usage_tracker: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    # Provider identification
    provider_name: str = "base"
    provider_type: ProviderType = ProviderType.LLM

    # Available models with their tiers and costs
    models: dict[str, dict[str, Any]] = {}

    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig()
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        """Validate provider configuration. Override in subclasses."""
        pass

    @trace_span("LLM.generate")
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """
        Generate text from a prompt.

        Args:
            prompt: The user prompt/message
            model: Model to use (defaults to provider's default)
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            **kwargs: Provider-specific options

        Returns:
            GenerationResult with generated text and metadata

        Raises:
            ProviderError: On generation failure
            RateLimitError: When rate limited
            AuthenticationError: When API key is invalid
        """
        pass

    @trace_span("LLM.generate_stream")
    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        """
        Generate text with streaming.

        Yields:
            str: Token chunks as they're generated

        Note: Default implementation calls generate() and yields full result.
        Override in subclasses for true streaming.
        """
        result = await self.generate(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        yield result.text

    @trace_span("LLM.chat")
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = "auto",
        **kwargs: Any,
    ) -> Any:
        """
        Direct chat completion with tool support.
        
        Returns raw provider response (e.g. ChatCompletion object).
        """
        raise NotImplementedError("Provider does not support chat/tools.")


    def get_model_info(self, model: str) -> dict[str, Any]:
        """Get information about a specific model."""
        return self.models.get(model, {})

    def get_default_model(self, tier: ProviderTier = ProviderTier.STANDARD) -> str:
        """Get the default model for a given tier."""
        for model_name, info in self.models.items():
            if info.get("tier") == tier:
                return model_name
        # Fallback to first available model
        return next(iter(self.models.keys()), "")

    def estimate_cost(self, usage: TokenUsage, model: str) -> float:
        """Estimate cost based on token usage."""
        info = self.get_model_info(model)
        input_cost = info.get("input_cost_per_1k", 0) * usage.input_tokens / 1000
        output_cost = info.get("output_cost_per_1k", 0) * usage.output_tokens / 1000
        return input_cost + output_cost


class BaseEmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    provider_name: str = "base"
    provider_type: ProviderType = ProviderType.EMBEDDING

    # Available models with dimensions and costs
    models: dict[str, dict[str, Any]] = {}

    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig()
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        """Validate provider configuration. Override in subclasses."""
        pass

    @trace_span("Embedding.embed")
    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        dimensions: int | None = None,
        **kwargs: Any,
    ) -> EmbeddingResult:
        """
        Generate embeddings for texts.

        Args:
            texts: List of texts to embed
            model: Model to use (defaults to provider's default)
            dimensions: Optional dimension reduction (Matryoshka)
            **kwargs: Provider-specific options

        Returns:
            EmbeddingResult with embeddings and metadata

        Raises:
            ProviderError: On embedding failure
            RateLimitError: When rate limited
        """
        pass

    async def embed_single(
        self,
        text: str,
        model: str | None = None,
        dimensions: int | None = None,
        **kwargs: Any,
    ) -> list[float]:
        """Convenience method for single text embedding."""
        result = await self.embed([text], model=model, dimensions=dimensions, **kwargs)
        return result.embeddings[0]

    def get_model_info(self, model: str) -> dict[str, Any]:
        """Get information about a specific model."""
        return self.models.get(model, {})

    def get_default_model(self) -> str:
        """Get the default embedding model."""
        return next(iter(self.models.keys()), "")

    def get_dimensions(self, model: str) -> int:
        """Get the embedding dimensions for a model."""
        return self.get_model_info(model).get("dimensions", 1536)


class BaseRerankerProvider(ABC):
    """Abstract base class for reranker providers."""

    provider_name: str = "base"
    provider_type: ProviderType = ProviderType.RERANKER

    models: dict[str, dict[str, Any]] = {}

    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig()

    @trace_span("Reranker.rerank")
    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> RerankResult:
        """
        Rerank documents by relevance to query.

        Args:
            query: The search query
            documents: List of documents to rerank
            model: Model to use
            top_k: Return only top K results
            **kwargs: Provider-specific options

        Returns:
            RerankResult with scored and sorted documents
        """
        pass
