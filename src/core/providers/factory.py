"""
Provider Factory
================

Factory pattern for provider instantiation with failover support.
"""

import logging
from dataclasses import dataclass, field

from src.core.database.session import async_session_maker
from src.core.providers.base import (
    BaseEmbeddingProvider,
    BaseLLMProvider,
    BaseRerankerProvider,
    ProviderConfig,
    ProviderTier,
    ProviderUnavailableError,
)
from src.core.providers.failover import FailoverEmbeddingProvider, FailoverLLMProvider
from src.core.services.usage_tracker import UsageTracker

logger = logging.getLogger(__name__)


@dataclass
class ProviderRegistry:
    """Registry of available providers."""

    llm_providers: dict[str, type[BaseLLMProvider]] = field(default_factory=dict)
    embedding_providers: dict[str, type[BaseEmbeddingProvider]] = field(default_factory=dict)
    reranker_providers: dict[str, type[BaseRerankerProvider]] = field(default_factory=dict)


# Global registry
_registry = ProviderRegistry()


def register_llm_provider(name: str, provider_class: type[BaseLLMProvider]):
    """Register an LLM provider."""
    _registry.llm_providers[name] = provider_class


def register_embedding_provider(name: str, provider_class: type[BaseEmbeddingProvider]):
    """Register an embedding provider."""
    _registry.embedding_providers[name] = provider_class


def register_reranker_provider(name: str, provider_class: type[BaseRerankerProvider]):
    """Register a reranker provider."""
    _registry.reranker_providers[name] = provider_class


# Auto-register providers on import
def _auto_register():
    """Auto-register all available providers."""
    # LLM providers
    try:
        from src.core.providers.openai import OpenAILLMProvider

        register_llm_provider("openai", OpenAILLMProvider)
    except ImportError:
        pass

    try:
        from src.core.providers.anthropic import AnthropicLLMProvider

        register_llm_provider("anthropic", AnthropicLLMProvider)
    except ImportError:
        pass

    # Embedding providers
    try:
        from src.core.providers.openai import OpenAIEmbeddingProvider

        register_embedding_provider("openai", OpenAIEmbeddingProvider)
    except ImportError:
        pass

    try:
        from src.core.providers.local import LocalEmbeddingProvider

        register_embedding_provider("local", LocalEmbeddingProvider)
    except ImportError:
        pass

    # Reranker providers
    try:
        from src.core.providers.local import FlashRankReranker

        register_reranker_provider("flashrank", FlashRankReranker)
    except ImportError:
        pass

    try:
        from src.core.providers.ollama import OllamaLLMProvider, OllamaEmbeddingProvider

        register_llm_provider("ollama", OllamaLLMProvider)
        register_embedding_provider("ollama", OllamaEmbeddingProvider)
    except ImportError:
        pass


_auto_register()


class ProviderFactory:
    """
    Factory for creating configured providers.

    Usage:
        factory = ProviderFactory(openai_key="sk-...", anthropic_key="sk-...")
        llm = factory.get_llm_provider(tier=ProviderTier.ECONOMY)
        embeddings = factory.get_embedding_provider()
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        ollama_base_url: str | None = None,
        default_llm_provider: str | None = None,
        default_llm_model: str | None = None,
        default_llm_tier: ProviderTier = ProviderTier.ECONOMY,
        default_embedding_provider: str | None = None,
        default_embedding_model: str | None = None,
        enable_local_fallback: bool = True,
    ):
        self.openai_api_key = openai_api_key
        self.anthropic_api_key = anthropic_api_key
        self.ollama_base_url = ollama_base_url
        self.default_llm_provider = default_llm_provider
        self.default_llm_model = default_llm_model
        self.default_llm_tier = default_llm_tier
        self.default_embedding_provider = default_embedding_provider
        self.default_embedding_model = default_embedding_model
        self.enable_local_fallback = enable_local_fallback

        # Initialize Usage Tracker
        self.usage_tracker = UsageTracker(session_factory=async_session_maker)

        # Cache instantiated providers
        self._llm_cache: dict[str, BaseLLMProvider] = {}
        self._embedding_cache: dict[str, BaseEmbeddingProvider] = {}
        self._reranker_cache: dict[str, BaseRerankerProvider] = {}

    def get_llm_provider(
        self,
        provider_name: str | None = None,
        tier: ProviderTier | None = None,
        with_failover: bool = True,
        model_tier: ProviderTier | None = None, # Alias for backward compatibility
    ) -> BaseLLMProvider:
        """
        Get an LLM provider.

        Args:
            provider_name: Specific provider to use
            tier: Cost tier preference
            with_failover: Enable automatic failover
            model_tier: Alias for tier (Phase 5 compatibility)

        Returns:
            LLM provider instance
        """
        tier = tier or model_tier or self.default_llm_tier

        if provider_name:
            return self._create_llm_provider(provider_name, model=model_tier) # model_tier might be passed as model alias

        # Check for explicit default provider
        if self.default_llm_provider:
             return self._create_llm_provider(
                 self.default_llm_provider,
                 model=self.default_llm_model
             )

        # Build failover chain based on available keys
        providers = []

        # Primary based on tier
        if tier == ProviderTier.ECONOMY:
            if self.openai_api_key:
                providers.append(self._create_llm_provider("openai", model="gpt-4o-mini"))
            if self.anthropic_api_key:
                providers.append(self._create_llm_provider("anthropic", model="claude-3-5-haiku-20241022"))
        elif tier == ProviderTier.STANDARD:
            if self.openai_api_key:
                providers.append(self._create_llm_provider("openai", model="gpt-4o"))
            if self.anthropic_api_key:
                providers.append(self._create_llm_provider("anthropic", model="claude-sonnet-4-20250514"))
        elif tier == ProviderTier.PREMIUM:
            if self.anthropic_api_key:
                providers.append(self._create_llm_provider("anthropic", model="claude-3-opus-20240229"))
            if self.openai_api_key:
                providers.append(self._create_llm_provider("openai", model="o1"))

        if not providers:
            raise ProviderUnavailableError(
                "No LLM providers available. Please configure API keys.",
                provider="factory",
            )

        if with_failover and len(providers) > 1:
            return FailoverLLMProvider(providers)

        return providers[0]

    def get_embedding_provider(
        self,
        provider_name: str | None = None,
        with_failover: bool = True,
    ) -> BaseEmbeddingProvider:
        """Get an embedding provider."""
        if provider_name:
            return self._create_embedding_provider(provider_name)

        # Check for explicit default embedding provider configuration
        if self.default_embedding_provider:
            logger.info(f"Using configured embedding provider: {self.default_embedding_provider}")
            return self._create_embedding_provider(self.default_embedding_provider)

        providers = []

        # Prefer OpenAI for cost-effectiveness
        if self.openai_api_key:
            providers.append(self._create_embedding_provider("openai"))

        # Local fallback
        if self.enable_local_fallback:
            try:
                providers.append(self._create_embedding_provider("local"))
            except Exception:
                pass  # Local not available

        if not providers:
            raise ProviderUnavailableError(
                "No embedding providers available.",
                provider="factory",
            )

        if with_failover and len(providers) > 1:
            return FailoverEmbeddingProvider(providers)

        return providers[0]

    def get_reranker_provider(
        self,
        provider_name: str = "flashrank",
    ) -> BaseRerankerProvider:
        """Get a reranker provider."""
        return self._create_reranker_provider(provider_name)

    def _create_llm_provider(
        self,
        name: str,
        model: str | None = None,
    ) -> BaseLLMProvider:
        """Create an LLM provider instance."""
        cache_key = f"{name}:{model}"
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]

        provider_class = _registry.llm_providers.get(name)
        if not provider_class:
            raise ValueError(f"Unknown LLM provider: {name}")

        # Get API key for provider
        api_key = None
        if name == "openai":
            api_key = self.openai_api_key
        elif name == "anthropic":
            api_key = self.anthropic_api_key
        if name == "ollama":
            api_key = "ollama"  # placeholder

        base_url = None
        if name == "ollama":
            base_url = self.ollama_base_url

        config = ProviderConfig(
            api_key=api_key,
            base_url=base_url,
            usage_tracker=self.usage_tracker
        )
        provider = provider_class(config)

        # Override default model if specified
        if model:
            provider.default_model = model

        self._llm_cache[cache_key] = provider
        return provider

    def _create_embedding_provider(self, name: str) -> BaseEmbeddingProvider:
        """Create an embedding provider instance."""
        if name in self._embedding_cache:
            return self._embedding_cache[name]

        provider_class = _registry.embedding_providers.get(name)
        if not provider_class:
            raise ValueError(f"Unknown embedding provider: {name}")

        # Build config based on provider type
        api_key = None
        base_url = None

        if name == "openai":
            api_key = self.openai_api_key
        elif name == "ollama":
            api_key = "ollama"  # Placeholder, not used by Ollama
            base_url = self.ollama_base_url

        config = ProviderConfig(
            api_key=api_key,
            base_url=base_url,
            usage_tracker=self.usage_tracker
        )
        provider = provider_class(config)

        # Override default model if configured
        if self.default_embedding_model:
            provider.default_model = self.default_embedding_model

        self._embedding_cache[name] = provider
        return provider

    def _create_reranker_provider(self, name: str) -> BaseRerankerProvider:
        """Create a reranker provider instance."""
        if name in self._reranker_cache:
            return self._reranker_cache[name]

        provider_class = _registry.reranker_providers.get(name)
        if not provider_class:
            raise ValueError(f"Unknown reranker provider: {name}")

        provider = provider_class()
        self._reranker_cache[name] = provider
        return provider


# =============================================================================
# Convenience Functions
# =============================================================================

_default_factory: ProviderFactory | None = None


def init_providers(
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    ollama_base_url: str | None = None,
    default_llm_provider: str | None = None,
    default_llm_model: str | None = None,
    default_embedding_provider: str | None = None,
    default_embedding_model: str | None = None,
    **kwargs,
) -> ProviderFactory:
    """Initialize the default provider factory."""
    global _default_factory
    _default_factory = ProviderFactory(
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        ollama_base_url=ollama_base_url,
        default_llm_provider=default_llm_provider,
        default_llm_model=default_llm_model,
        default_embedding_provider=default_embedding_provider,
        default_embedding_model=default_embedding_model,
        **kwargs,
    )
    return _default_factory


def get_llm_provider(
    tier: ProviderTier = ProviderTier.ECONOMY,
    **kwargs,
) -> BaseLLMProvider:
    """Get an LLM provider from the default factory."""
    if _default_factory is None:
        raise RuntimeError("Providers not initialized. Call init_providers() first.")
    return _default_factory.get_llm_provider(tier=tier, **kwargs)


def get_embedding_provider(**kwargs) -> BaseEmbeddingProvider:
    """Get an embedding provider from the default factory."""
    if _default_factory is None:
        raise RuntimeError("Providers not initialized. Call init_providers() first.")
    return _default_factory.get_embedding_provider(**kwargs)


def get_reranker_provider(**kwargs) -> BaseRerankerProvider:
    """Get a reranker provider from the default factory."""
    if _default_factory is None:
        raise RuntimeError("Providers not initialized. Call init_providers() first.")
    return _default_factory.get_reranker_provider(**kwargs)
