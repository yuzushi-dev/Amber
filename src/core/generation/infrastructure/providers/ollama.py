"""
Ollama Provider
===============

LLM provider implementation for Ollama API (OpenAI compatible).
"""

import logging
import time
from typing import Any

from src.core.generation.infrastructure.providers.base import (
    AuthenticationError,
    BaseEmbeddingProvider,
    BaseLLMProvider,
    EmbeddingResult,
    GenerationResult,
    InvalidRequestError,
    ProviderConfig,
    ProviderTier,
    ProviderUnavailableError,
    RateLimitError,
    TokenUsage,
)
from src.shared.kernel.observability import trace_span
from src.shared.context import get_current_tenant, get_request_id

try:
    from opentelemetry import trace
except ImportError:
    # Mock trace
    class MockContext:
        trace_id = 0
        is_valid = False

    class MockSpan:
        def get_span_context(self):
            return MockContext()

    class MockTrace:
        def get_current_span(self):
            return MockSpan()

    trace = MockTrace()

logger = logging.getLogger(__name__)

# Lazy import
_openai_client = None


def _get_openai_client(api_key: str, base_url: str):
    """Get or create OpenAI client configured for Ollama."""
    global _openai_client
    try:
        from openai import AsyncOpenAI

        # API key is required by client but ignored by Ollama
        return AsyncOpenAI(api_key=api_key or "ollama", base_url=base_url)
    except ImportError as e:
        raise ImportError("openai package is required. Install with: pip install openai>=1.10.0") from e


class OllamaLLMProvider(BaseLLMProvider):
    """Ollama LLM provider."""

    provider_name = "ollama"

    # Common Ollama models (can be overridden by config)
    models = {
        "llama3": {
            "tier": ProviderTier.LOCAL,
            "description": "Meta Llama 3",
        },
        "mistral": {
            "tier": ProviderTier.LOCAL,
            "description": "Mistral 7B",
        },
        "phi3": {
            "tier": ProviderTier.LOCAL,
            "description": "Microsoft Phi-3",
        },
    }

    default_model = "llama3"

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        import os
        # Allow overriding default model via env
        self.default_model = os.getenv("OLLAMA_MODEL", self.default_model)
        self._client = None
        # Default Ollama URL if not provided
        if not self.config.base_url:
            self.config.base_url = "http://localhost:11434/v1"

    def _validate_config(self) -> None:
        # Ollama doesn't strictly require API key, but base_url is important
        pass

    @property
    def model_name(self) -> str:
        """Get the current model name."""
        return self.default_model

    @property
    def client(self):
        if self._client is None:
            self._client = _get_openai_client(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
        return self._client

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
        """Generate text using Ollama (via OpenAI compatible API)."""
        model = model or self.default_model
        start_time = time.perf_counter()

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                **kwargs,
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Extract usage
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            )

            # Get response text
            text = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason

            result = GenerationResult(
                text=text,
                model=model,
                provider=self.provider_name,
                usage=usage,
                finish_reason=finish_reason,
                latency_ms=elapsed_ms,
                cost_estimate=0.0,  # Local is usually free
                metadata={"response_id": response.id},
            )

            # Record usage if tracker is available
            if self.config.usage_tracker:
                span_context = trace.get_current_span().get_span_context()
                trace_id = format(span_context.trace_id, '032x') if span_context.is_valid else None

                await self.config.usage_tracker.record_usage(
                    tenant_id=get_current_tenant() or "default",
                    operation="generation",
                    provider=self.provider_name,
                    model=model,
                    usage=usage,
                    cost=result.cost_estimate,
                    request_id=get_request_id(),
                    trace_id=trace_id,
                    metadata=result.metadata
                )

            return result

        except Exception as e:
            self._handle_error(e, model)

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
        """
        model = self.default_model
        
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                **kwargs,
            )
            return response
            
        except Exception as e:
            self._handle_error(e, model)

    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        """Stream text generation."""
        model = model or self.default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **{k: v for k, v in kwargs.items() if k != 'history'},
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            self._handle_error(e, model)

    def _handle_error(self, e: Exception, model: str) -> None:
        """Convert OpenAI exceptions to provider exceptions."""
        error_type = type(e).__name__

        if "RateLimitError" in error_type:
            raise RateLimitError(
                str(e),
                provider=self.provider_name,
                model=model,
                retry_after=60.0,
            )
        elif "AuthenticationError" in error_type:
            raise AuthenticationError(
                str(e),
                provider=self.provider_name,
                model=model,
            )
        elif "BadRequestError" in error_type or "InvalidRequestError" in error_type:
            raise InvalidRequestError(
                str(e),
                provider=self.provider_name,
                model=model,
            )
        elif "APIConnectionError" in error_type or "Timeout" in error_type:
            raise ProviderUnavailableError(
                str(e),
                provider=self.provider_name,
                model=model,
            )
        else:
            # Re-raise as generic provider error
            raise ProviderUnavailableError(
                f"Unexpected error: {e}",
                provider=self.provider_name,
                model=model,
            )


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """
    Ollama embedding provider using OpenAI-compatible API.

    Supports local embedding models like nomic-embed-text, mxbai-embed-large.
    """

    provider_name = "ollama"

    models = {
        "nomic-embed-text": {
            "dimensions": 768,
            "max_dimensions": 768,
            "cost_per_1k": 0.0,  # Free/local
            "description": "Nomic's high quality text embeddings",
        },
        "mxbai-embed-large": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,
            "description": "MixedBread AI large embeddings",
        },
        "all-minilm": {
            "dimensions": 384,
            "max_dimensions": 384,
            "cost_per_1k": 0.0,
            "description": "Fast, lightweight embeddings",
        },
        "snowflake-arctic-embed": {
            "dimensions": 1024,
            "max_dimensions": 1024,
            "cost_per_1k": 0.0,
            "description": "Snowflake Arctic embeddings",
        },
    }

    default_model = "nomic-embed-text"

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        import os

        # Allow overriding default model via env
        self.default_model = os.getenv("OLLAMA_EMBEDDING_MODEL", self.default_model)
        self._client = None
        # Default Ollama URL if not provided
        if not self.config.base_url:
            self.config.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    def _validate_config(self) -> None:
        # Ollama doesn't strictly require API key, but base_url is important
        pass

    @property
    def client(self):
        if self._client is None:
            self._client = _get_openai_client(
                api_key=self.config.api_key or "ollama",
                base_url=self.config.base_url,
            )
        return self._client

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        dimensions: int | None = None,
        **kwargs,
    ) -> EmbeddingResult:
        """Generate embeddings using Ollama (via OpenAI compatible API)."""
        model = model or self.default_model
        start_time = time.perf_counter()

        try:
            response = await self.client.embeddings.create(
                model=model,
                input=texts,
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Extract embeddings in order
            embeddings = [
                item.embedding for item in sorted(response.data, key=lambda x: x.index)
            ]

            # Get dimensions from first embedding
            actual_dimensions = len(embeddings[0]) if embeddings else 0

            usage = TokenUsage(
                input_tokens=response.usage.total_tokens if response.usage else 0,
                output_tokens=0,
            )

            return EmbeddingResult(
                embeddings=embeddings,
                model=model,
                provider=self.provider_name,
                usage=usage,
                dimensions=actual_dimensions,
                latency_ms=elapsed_ms,
                cost_estimate=0.0,  # Local is free
            )

        except Exception as e:
            self._handle_error(e, model)

    def _handle_error(self, e: Exception, model: str) -> None:
        """Convert OpenAI exceptions to provider exceptions."""
        error_type = type(e).__name__

        if "RateLimitError" in error_type:
            raise RateLimitError(
                str(e),
                provider=self.provider_name,
                model=model,
                retry_after=60.0,
            )
        elif "AuthenticationError" in error_type:
            raise AuthenticationError(
                str(e),
                provider=self.provider_name,
                model=model,
            )
        elif "APIConnectionError" in error_type or "Timeout" in error_type:
            raise ProviderUnavailableError(
                f"Cannot connect to Ollama at {self.config.base_url}: {e}",
                provider=self.provider_name,
                model=model,
            )
        else:
            raise ProviderUnavailableError(
                f"Embedding error: {e}",
                provider=self.provider_name,
                model=model,
            )
