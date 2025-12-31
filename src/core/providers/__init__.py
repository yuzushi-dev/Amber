"""
Model Providers
===============

Unified interface for LLM and Embedding providers with failover support.
"""

from src.core.providers.base import (
    BaseLLMProvider,
    BaseEmbeddingProvider,
    BaseRerankerProvider,
    GenerationResult,
    EmbeddingResult,
    RerankResult,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
# from src.core.providers.factory import (
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
