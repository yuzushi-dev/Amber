"""
Model Providers
===============

Unified interface for LLM and Embedding providers with failover support.
"""

from src.core.generation.infrastructure.providers.base import (
    BaseEmbeddingProvider,
    BaseLLMProvider,
    BaseRerankerProvider,
    EmbeddingResult,
    GenerationResult,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
    RerankResult,
)

# from src.core.generation.infrastructure.providers.factory import (
#     ProviderFactory,
#     get_llm_provider,
#     get_embedding_provider,
#     get_reranker_provider,
# )

__all__ = [
    # Base classes
    "BaseLLMProvider",
    "BaseEmbeddingProvider",
    "BaseRerankerProvider",
    # Result types
    "GenerationResult",
    "EmbeddingResult",
    "RerankResult",
    # Exceptions
    "ProviderError",
    "ProviderUnavailableError",
    "RateLimitError",
    # Factory (Import directly from factory module)
    # "ProviderFactory",
    # "get_llm_provider",
    # "get_embedding_provider",
    # "get_reranker_provider",
]
