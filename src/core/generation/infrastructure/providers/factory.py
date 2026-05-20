"""
Provider Factory
================

Factory pattern for provider instantiation with failover support.
"""

import logging
from dataclasses import dataclass, field

from src.core.admin_ops.application.usage_tracker import UsageTracker
from src.core.database.session import async_session_maker
from src.core.generation.domain.ports.provider_factory import (
    set_provider_factory,
    set_provider_factory_builder,
)
from src.core.generation.infrastructure.providers.base import (
    BaseEmbeddingProvider,
    BaseLLMProvider,
    BaseRerankerProvider,
    ProviderConfig,
    ProviderTier,
    ProviderUnavailableError,
)
from src.core.generation.infrastructure.providers.failover import (
    FailoverEmbeddingProvider,
    FailoverLLMProvider,
)
from src.core.generation.infrastructure.providers.load_balanced import LoadBalancedLLMProvider
from src.shared.model_registry import (
    DEFAULT_EMBEDDING_FALLBACK,
    DEFAULT_LLM_FALLBACKS,
    EMBEDDING_MODEL_TO_PROVIDERS,
    LLM_MODEL_TO_PROVIDERS,
    parse_fallback_chain,
    resolve_provider_for_model,
)

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
        from src.core.generation.infrastructure.providers.openai import OpenAILLMProvider

        register_llm_provider("openai", OpenAILLMProvider)
    except ImportError:
        pass

    try:
        from src.core.generation.infrastructure.providers.anthropic import AnthropicLLMProvider

        register_llm_provider("anthropic", AnthropicLLMProvider)
    except ImportError:
        pass

    # Embedding providers
    try:
        from src.core.generation.infrastructure.providers.openai import OpenAIEmbeddingProvider

        register_embedding_provider("openai", OpenAIEmbeddingProvider)
    except ImportError:
        pass

    try:
        from src.core.generation.infrastructure.providers.local import LocalEmbeddingProvider

        register_embedding_provider("local", LocalEmbeddingProvider)
    except ImportError:
        pass

    # Reranker providers
    try:
        from src.core.generation.infrastructure.providers.local import FlashRankReranker

        register_reranker_provider("flashrank", FlashRankReranker)
    except ImportError:
        pass

    try:
        from src.core.generation.infrastructure.providers.ollama import (
            OllamaEmbeddingProvider,
            OllamaLLMProvider,
        )

        register_llm_provider("ollama", OllamaLLMProvider)
        register_embedding_provider("ollama", OllamaEmbeddingProvider)
    except ImportError:
        pass

    # OpenAI-compatible fallback providers
    try:
        from src.core.generation.infrastructure.providers.openai import OpenAILLMProvider

        register_llm_provider("nvidia_nim", OpenAILLMProvider)
        register_llm_provider("openrouter", OpenAILLMProvider)
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
        llm_fallback_local: str | None = None,
        llm_fallback_economy: str | None = None,
        llm_fallback_standard: str | None = None,
        llm_fallback_premium: str | None = None,
        embedding_fallback_order: str | None = None,
        enable_local_fallback: bool = True,
        # Fallback provider keys
        openrouter_api_key: str | None = None,
        openrouter_base_url: str | None = None,
        nvidia_nim_api_key: str | None = None,
        nvidia_nim_base_url: str | None = None,
        llm_fallback_enabled: bool = True,
        # Ollama Cloud (direct API, bypasses local daemon)
        ollama_cloud_base_url: str | None = None,
        ollama_cloud_api_keys: list[str] | None = None,
    ):
        self.openai_api_key = openai_api_key
        self.anthropic_api_key = anthropic_api_key
        self.ollama_base_url = ollama_base_url
        self.default_llm_provider = default_llm_provider
        self.default_llm_model = default_llm_model
        self.default_llm_tier = default_llm_tier
        self.default_embedding_provider = default_embedding_provider
        self.default_embedding_model = default_embedding_model
        self.llm_fallback_local = llm_fallback_local
        self.llm_fallback_economy = llm_fallback_economy
        self.llm_fallback_standard = llm_fallback_standard
        self.llm_fallback_premium = llm_fallback_premium
        self.embedding_fallback_order = embedding_fallback_order
        self.enable_local_fallback = enable_local_fallback
        # Fallback providers
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_base_url = openrouter_base_url or "https://openrouter.ai/api/v1"
        self.nvidia_nim_api_key = nvidia_nim_api_key
        self.nvidia_nim_base_url = nvidia_nim_base_url or "https://integrate.api.nvidia.com/v1"
        self.llm_fallback_enabled = llm_fallback_enabled
        # Ollama Cloud
        self.ollama_cloud_base_url = ollama_cloud_base_url or "https://ollama.com/v1"
        self.ollama_cloud_api_keys: list[str] = ollama_cloud_api_keys or []

        # Initialize Usage Tracker
        self.usage_tracker = UsageTracker(session_factory=async_session_maker)

        # Cache instantiated providers
        self._llm_cache: dict[str, BaseLLMProvider] = {}
        self._embedding_cache: dict[str, BaseEmbeddingProvider] = {}
        self._reranker_cache: dict[str, BaseRerankerProvider] = {}
        # Single-slot cache for the ollama_cloud key-pool wrapper
        self._ollama_cloud_wrapper: BaseLLMProvider | None = None

    def update_ollama_base_url(self, url: str | None) -> None:
        """Update Ollama base URL at runtime (called on tenant config change).

        Clears cached Ollama providers so they are recreated with the new URL.
        """
        self.ollama_base_url = url
        # Clear cached Ollama providers so next request uses updated URL
        self._llm_cache.pop("ollama", None)
        self._embedding_cache.pop("ollama", None)

    def get_llm_provider(
        self,
        provider_name: str | None = None,
        tier: ProviderTier | None = None,
        model: str | None = None,
        with_failover: bool = True,
        model_tier: ProviderTier | None = None,  # Alias for backward compatibility
    ) -> BaseLLMProvider:
        """
        Get an LLM provider.

        Args:
            provider_name: Specific provider to use
            tier: Cost tier preference
            model: Explicit model override for the provider
            with_failover: Enable automatic failover
            model_tier: Alias for tier (Phase 5 compatibility)

        Returns:
            LLM provider instance
        """
        tier = tier or model_tier or self.default_llm_tier

        if model and not provider_name:
            provider_name = resolve_provider_for_model(model, LLM_MODEL_TO_PROVIDERS, kind="llm")

        if model and not provider_name:
            # Model not in registry — use the configured default provider
            # and pass the model through. The provider will give a clear
            # error if the model doesn't exist.
            provider_name = self.default_llm_provider

        if provider_name:
            primary = self._create_llm_provider(provider_name, model=model)
            # If fallbacks enabled, wrap with fallback chain
            if self.llm_fallback_enabled and with_failover:
                chain = parse_fallback_chain(None, default=DEFAULT_LLM_FALLBACKS.get(tier, []))
                logger.info(
                    f"Building failover chain: primary={provider_name}, tier={tier}, "
                    f"chain={chain}, nim_key={'YES' if self.nvidia_nim_api_key else 'NO'}, "
                    f"or_key={'YES' if self.openrouter_api_key else 'NO'}"
                )
                providers = [primary]
                for fb_provider, fb_model in chain:
                    if fb_provider == provider_name:
                        continue  # Skip — already the primary
                    if not self._is_llm_provider_available(fb_provider):
                        logger.info(f"Skipping unavailable fallback provider: {fb_provider}")
                        continue
                    providers.append(self._create_llm_provider(fb_provider, model=fb_model))
                logger.info(f"Final failover chain: {[p.provider_name for p in providers]}")
                if len(providers) > 1:
                    return FailoverLLMProvider(providers)
            return primary

        # Check for explicit default provider
        if self.default_llm_provider:
            primary = self._create_llm_provider(
                self.default_llm_provider, model=self.default_llm_model
            )
            # If fallbacks disabled, return primary only
            if not self.llm_fallback_enabled:
                return primary
            # Build fallback chain behind the primary
            fallback_value = {
                ProviderTier.LOCAL: self.llm_fallback_local,
                ProviderTier.ECONOMY: self.llm_fallback_economy,
                ProviderTier.STANDARD: self.llm_fallback_standard,
                ProviderTier.PREMIUM: self.llm_fallback_premium,
            }.get(tier)
            chain = parse_fallback_chain(fallback_value, default=DEFAULT_LLM_FALLBACKS[tier])
            providers = [primary]
            for fb_provider, model_name in chain:
                if fb_provider == self.default_llm_provider:
                    continue  # Skip the primary — already first in the list
                if not self._is_llm_provider_available(fb_provider):
                    continue
                providers.append(self._create_llm_provider(fb_provider, model=model_name))
            if with_failover and len(providers) > 1:
                return FailoverLLMProvider(providers)
            return providers[0]

        fallback_value = {
            ProviderTier.LOCAL: self.llm_fallback_local,
            ProviderTier.ECONOMY: self.llm_fallback_economy,
            ProviderTier.STANDARD: self.llm_fallback_standard,
            ProviderTier.PREMIUM: self.llm_fallback_premium,
        }.get(tier)

        chain = parse_fallback_chain(fallback_value, default=DEFAULT_LLM_FALLBACKS[tier])
        providers = []
        for provider, model_name in chain:
            if not self._is_llm_provider_available(provider):
                continue
            providers.append(self._create_llm_provider(provider, model=model_name))

        if not providers:
            raise ProviderUnavailableError(
                "No LLM providers available. Please configure API keys or Ollama.",
                provider="factory",
            )

        if not self.llm_fallback_enabled:
            return providers[0]

        if with_failover and len(providers) > 1:
            return FailoverLLMProvider(providers)

        return providers[0]

    def _is_llm_provider_available(self, provider: str) -> bool:
        """Check if a provider has the necessary credentials configured."""
        if provider == "openai" and not self.openai_api_key:
            return False
        if provider == "anthropic" and not self.anthropic_api_key:
            return False
        if provider == "ollama" and not self.ollama_base_url:
            return False
        if provider == "ollama_cloud" and not self.ollama_cloud_api_keys:
            return False
        if provider == "nvidia_nim" and not self.nvidia_nim_api_key:
            return False
        if provider == "openrouter" and not self.openrouter_api_key:
            return False
        return True

    def get_embedding_provider(
        self,
        provider_name: str | None = None,
        with_failover: bool = True,
        model: str | None = None,
    ) -> BaseEmbeddingProvider:
        """Get an embedding provider."""
        if model and not provider_name:
            provider_name = resolve_provider_for_model(
                model, EMBEDDING_MODEL_TO_PROVIDERS, kind="embedding"
            )

        if model and not provider_name:
            # Model not in registry — use the configured default provider
            provider_name = self.default_embedding_provider

        if provider_name:
            return self._create_embedding_provider(provider_name, model=model)

        # Check for explicit default embedding provider configuration
        if self.default_embedding_provider:
            logger.info(f"Using configured embedding provider: {self.default_embedding_provider}")
            return self._create_embedding_provider(
                self.default_embedding_provider, model=model or self.default_embedding_model
            )

        chain = parse_fallback_chain(
            self.embedding_fallback_order,
            default=DEFAULT_EMBEDDING_FALLBACK,
        )
        providers = []
        for provider, model_name in chain:
            if provider == "openai" and not self.openai_api_key:
                continue
            if provider == "ollama" and not self.ollama_base_url:
                continue
            if provider == "local" and not self.enable_local_fallback:
                continue
            providers.append(self._create_embedding_provider(provider, model=model_name))

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
        from src.shared.model_registry import DEFAULT_LLM_MODEL

        # Ollama Cloud: build a key-pool backed by FailoverLLMProvider, cached in a single slot.
        if name == "ollama_cloud":
            if self._ollama_cloud_wrapper is not None:
                if model:
                    primary = (
                        self._ollama_cloud_wrapper.providers[0]
                        if hasattr(self._ollama_cloud_wrapper, "providers")
                        else self._ollama_cloud_wrapper
                    )
                    primary.default_model = model
                return self._ollama_cloud_wrapper
            if not self.ollama_cloud_api_keys:
                raise ProviderUnavailableError(
                    "ollama_cloud requested but OLLAMA_CLOUD_API_KEYS is empty",
                    provider="ollama_cloud",
                )
            from src.core.generation.infrastructure.providers.ollama import OllamaLLMProvider
            pool: list[BaseLLMProvider] = []
            for i, key in enumerate(self.ollama_cloud_api_keys):
                cfg = ProviderConfig(
                    api_key=key,
                    base_url=self.ollama_cloud_base_url,
                    usage_tracker=self.usage_tracker,
                )
                inst = OllamaLLMProvider(cfg, use_capacity_limiter=False, use_native_options=False)
                inst.provider_name = f"ollama_cloud_{i}"
                if model:
                    inst.default_model = model
                elif "ollama_cloud" in DEFAULT_LLM_MODEL:
                    inst.default_model = DEFAULT_LLM_MODEL["ollama_cloud"]
                pool.append(inst)
            self._ollama_cloud_wrapper = (
                pool[0] if len(pool) == 1 else LoadBalancedLLMProvider(pool)
            )
            return self._ollama_cloud_wrapper

        cache_key = f"{name}:{model}"
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]

        provider_class = _registry.llm_providers.get(name)
        if not provider_class:
            raise ValueError(f"Unknown LLM provider: {name}")

        # Get API key and base URL for provider
        api_key = None
        base_url = None

        if name == "openai":
            api_key = self.openai_api_key
        elif name == "anthropic":
            api_key = self.anthropic_api_key
        elif name == "ollama":
            api_key = "ollama"  # placeholder
            base_url = self.ollama_base_url
        elif name == "nvidia_nim":
            api_key = self.nvidia_nim_api_key
            base_url = self.nvidia_nim_base_url
        elif name == "openrouter":
            api_key = self.openrouter_api_key
            base_url = self.openrouter_base_url

        config = ProviderConfig(
            api_key=api_key, base_url=base_url, usage_tracker=self.usage_tracker
        )

        # OpenRouter requires extra HTTP headers for free-tier models
        if name == "openrouter":
            config.extra["default_headers"] = {
                "HTTP-Referer": "https://amber.local",
                "X-Title": "Amber RAG",
            }

        provider = provider_class(config)
        provider.provider_name = name

        # Override default model if specified, or use the registry default
        if model:
            provider.default_model = model
        elif name in DEFAULT_LLM_MODEL:
            provider.default_model = DEFAULT_LLM_MODEL[name]

        self._llm_cache[cache_key] = provider
        return provider

    def _create_embedding_provider(
        self, name: str, model: str | None = None
    ) -> BaseEmbeddingProvider:
        """Create an embedding provider instance."""
        # Use composite cache key to support different models per provider
        cache_key = f"{name}:{model}" if model else f"{name}:{self.default_embedding_model}"
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

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
            api_key=api_key, base_url=base_url, usage_tracker=self.usage_tracker
        )
        provider = provider_class(config)

        # Override default model if configured
        if model:
            provider.default_model = model
        elif self.default_embedding_model:
            provider.default_model = self.default_embedding_model

        self._embedding_cache[cache_key] = provider
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
    llm_fallback_local: str | None = None,
    llm_fallback_economy: str | None = None,
    llm_fallback_standard: str | None = None,
    llm_fallback_premium: str | None = None,
    embedding_fallback_order: str | None = None,
    openrouter_api_key: str | None = None,
    openrouter_base_url: str | None = None,
    nvidia_nim_api_key: str | None = None,
    nvidia_nim_base_url: str | None = None,
    llm_fallback_enabled: bool = True,
    ollama_cloud_base_url: str | None = None,
    ollama_cloud_api_keys: list[str] | None = None,
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
        llm_fallback_local=llm_fallback_local,
        llm_fallback_economy=llm_fallback_economy,
        llm_fallback_standard=llm_fallback_standard,
        llm_fallback_premium=llm_fallback_premium,
        embedding_fallback_order=embedding_fallback_order,
        openrouter_api_key=openrouter_api_key,
        openrouter_base_url=openrouter_base_url,
        nvidia_nim_api_key=nvidia_nim_api_key,
        nvidia_nim_base_url=nvidia_nim_base_url,
        llm_fallback_enabled=llm_fallback_enabled,
        ollama_cloud_base_url=ollama_cloud_base_url,
        ollama_cloud_api_keys=ollama_cloud_api_keys,
        **kwargs,
    )
    set_provider_factory_builder(ProviderFactory)
    set_provider_factory(_default_factory)
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
