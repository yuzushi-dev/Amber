"""
OpenAI Provider
===============

LLM and Embedding provider implementations for OpenAI API.
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
    # Mock trace for when opentelemetry is missing
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

# Lazy import to avoid import errors if openai not installed
_openai_client = None


def _get_openai_client(api_key: str, base_url: str | None = None):
    """Get or create OpenAI client."""
    global _openai_client
    try:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key, base_url=base_url)
    except ImportError as e:
        raise ImportError("openai package is required. Install with: pip install openai>=1.10.0") from e


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI LLM provider for GPT models."""

    provider_name = "openai"

    models = {
        "gpt-4o": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.005,  # $5/1M tokens
            "output_cost_per_1k": 0.015,  # $15/1M tokens
            "context_window": 128000,
            "description": "Most capable GPT-4 model",
        },
        "gpt-4o-mini": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00015,  # $0.15/1M tokens
            "output_cost_per_1k": 0.0006,  # $0.60/1M tokens
            "context_window": 128000,
            "description": "Fast and cost-effective",
        },
        "gpt-4-turbo": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.01,
            "output_cost_per_1k": 0.03,
            "context_window": 128000,
            "description": "GPT-4 Turbo with vision",
        },
        "o1": {
            "tier": ProviderTier.PREMIUM,
            "input_cost_per_1k": 0.015,
            "output_cost_per_1k": 0.06,
            "context_window": 200000,
            "description": "Reasoning model",
        },
    }

    default_model = "gpt-4o-mini"

    @property
    def model_name(self) -> str:
        """Return the current/default model name."""
        return self.default_model

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        self._client = None

    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise AuthenticationError(
                "API key is required",
                provider=self.provider_name,
            )

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
        seed: int | None = None,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate text using OpenAI ChatCompletion API."""
        model = model or self.default_model
        start_time = time.perf_counter()

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        logger.debug(f"[PROVIDER] openai.generate: model={model}, temp={temperature}, seed={seed}, prompt_len={len(prompt)}")

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
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
            
            system_fingerprint = response.system_fingerprint
            logger.debug(f"[PROVIDER] openai.response: fingerprint={system_fingerprint}, finish={finish_reason}")

            result = GenerationResult(
                text=text,
                model=model,
                provider=self.provider_name,
                usage=usage,
                finish_reason=finish_reason,
                latency_ms=elapsed_ms,
                cost_estimate=self.estimate_cost(usage, model),
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
        seed: int | None = None,
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
                seed=seed,
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
                retry_after=60.0,  # Default retry
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


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider."""

    provider_name = "openai"

    models = {
        "text-embedding-3-small": {
            "dimensions": 1536,
            "max_dimensions": 1536,
            "cost_per_1k": 0.00002,  # $0.02/1M tokens
            "description": "Efficient, cost-effective embeddings",
        },
        "text-embedding-3-large": {
            "dimensions": 3072,
            "max_dimensions": 3072,
            "cost_per_1k": 0.00013,  # $0.13/1M tokens
            "description": "High-quality embeddings with dimension flexibility",
        },
        "text-embedding-ada-002": {
            "dimensions": 1536,
            "max_dimensions": 1536,
            "cost_per_1k": 0.0001,  # $0.10/1M tokens (legacy)
            "description": "Legacy model",
        },
    }

    default_model = "text-embedding-3-small"

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        self._client = None

    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise AuthenticationError(
                "API key is required",
                provider=self.provider_name,
            )

    @property
    def client(self):
        if self._client is None:
            self._client = _get_openai_client(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
        return self._client

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        dimensions: int | None = None,
        **kwargs: Any,
    ) -> EmbeddingResult:
        """Generate embeddings for texts."""
        model = model or self.default_model
        start_time = time.perf_counter()

        # Prepare request
        request_params: dict[str, Any] = {
            "model": model,
            "input": texts,
        }

        # Support Matryoshka dimension reduction for v3 models
        if dimensions and "text-embedding-3" in model:
            request_params["dimensions"] = dimensions

        try:
            response = await self.client.embeddings.create(**request_params)

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Extract embeddings in order
            embeddings = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

            # Get dimensions from first embedding
            actual_dimensions = len(embeddings[0]) if embeddings else 0

            usage = TokenUsage(
                input_tokens=response.usage.total_tokens if response.usage else 0,
                output_tokens=0,
            )

            result = EmbeddingResult(
                embeddings=embeddings,
                model=model,
                provider=self.provider_name,
                usage=usage,
                dimensions=actual_dimensions,
                latency_ms=elapsed_ms,
                cost_estimate=usage.input_tokens * self.models.get(model, {}).get("cost_per_1k", 0) / 1000,
            )

                # Record usage if tracker is available
            if self.config.usage_tracker:
                span_context = trace.get_current_span().get_span_context()
                trace_id = format(span_context.trace_id, '032x') if span_context.is_valid else None
                
                # Merge metadata from kwargs (e.g. document_id) with result metadata
                usage_metadata = {**result.metadata, **(kwargs.get("metadata") or {})}

                await self.config.usage_tracker.record_usage(
                    tenant_id=get_current_tenant() or "default",
                    operation="embedding",
                    provider=self.provider_name,
                    model=model,
                    usage=usage,
                    cost=result.cost_estimate,
                    request_id=get_request_id(),
                    trace_id=trace_id,
                    metadata=usage_metadata,
                )

            return result

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
        else:
            raise ProviderUnavailableError(
                f"Embedding error: {e}",
                provider=self.provider_name,
                model=model,
            )
