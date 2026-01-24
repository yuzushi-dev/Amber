from collections.abc import AsyncIterator
from typing import Any, Protocol

from src.core.generation.domain.provider_models import EmbeddingResult, RerankResult


class LLMProviderPort(Protocol):
    provider_name: str
    model_name: str

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        ...

    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        ...

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = "auto",
        **kwargs: Any,
    ) -> Any:
        ...


class EmbeddingProviderPort(Protocol):
    provider_name: str

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        dimensions: int | None = None,
        **kwargs: Any,
    ) -> EmbeddingResult:
        ...

    def get_dimensions(self, model: str) -> int:
        ...


class RerankerProviderPort(Protocol):
    provider_name: str

    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> RerankResult:
        ...
