from collections.abc import Callable
from typing import Any, Protocol

from src.core.generation.domain.provider_models import ProviderTier
from src.core.generation.domain.ports.providers import (
    EmbeddingProviderPort,
    LLMProviderPort,
    RerankerProviderPort,
)


class ProviderFactoryPort(Protocol):
    def get_llm_provider(
        self,
        provider_name: str | None = None,
        tier: ProviderTier | None = None,
        **kwargs: Any,
    ) -> LLMProviderPort:
        ...

    def get_embedding_provider(
        self,
        provider_name: str | None = None,
        **kwargs: Any,
    ) -> EmbeddingProviderPort:
        ...

    def get_reranker_provider(
        self,
        provider_name: str | None = None,
        **kwargs: Any,
    ) -> RerankerProviderPort:
        ...


ProviderFactoryBuilder = Callable[..., ProviderFactoryPort]

_provider_factory: ProviderFactoryPort | None = None
_provider_factory_builder: ProviderFactoryBuilder | None = None


def set_provider_factory(factory: ProviderFactoryPort | None) -> None:
    global _provider_factory
    _provider_factory = factory


def set_provider_factory_builder(builder: ProviderFactoryBuilder | None) -> None:
    global _provider_factory_builder
    _provider_factory_builder = builder


def get_provider_factory() -> ProviderFactoryPort:
    if _provider_factory is None:
        raise RuntimeError("Provider factory not configured. Call set_provider_factory() at startup.")
    return _provider_factory


def build_provider_factory(**kwargs: Any) -> ProviderFactoryPort:
    if _provider_factory_builder is None:
        raise RuntimeError("Provider factory builder not configured. Call set_provider_factory_builder() at startup.")
    return _provider_factory_builder(**kwargs)


def get_llm_provider(
    tier: ProviderTier = ProviderTier.ECONOMY,
    **kwargs: Any,
) -> LLMProviderPort:
    return get_provider_factory().get_llm_provider(tier=tier, **kwargs)


def get_embedding_provider(**kwargs: Any) -> EmbeddingProviderPort:
    return get_provider_factory().get_embedding_provider(**kwargs)


def get_reranker_provider(**kwargs: Any) -> RerankerProviderPort:
    return get_provider_factory().get_reranker_provider(**kwargs)
