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
    ProviderConfig,
    ProviderUnavailableError,
    QuotaExceededError,
    RateLimitError,
    TokenUsage,
)
from src.shared.model_registry import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
    EMBEDDING_MODELS,
    LLM_MODELS,
    embedding_supports_dimensions,
    get_openai_chat_overrides,
)

try:
    from opentelemetry import trace
except ImportError:

    class MockTrace:
        def get_tracer(self, name):
            return MockTracer()

    class MockTracer:
        def start_as_current_span(self, name):
            return MockSpan()

    class MockSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    trace = MockTrace()

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

# Global client to allow connection pooling reuse
_openai_client = None


def _get_openai_client(api_key: str, base_url: str | None = None):
    """Get or create OpenAI client."""
    global _openai_client
    try:
        from openai import AsyncOpenAI

        # Check if we need to recreate (e.g. key change or not initialized)
        if _openai_client is None or _openai_client.api_key != api_key:
            _openai_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        return _openai_client
    except ImportError as e:
        raise ImportError(
            "openai package is required. Install with: pip install openai>=1.10.0"
        ) from e


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI LLM provider for GPT models."""

    provider_name = "openai"

    # Models supported by this provider for validation
    models = LLM_MODELS["openai"]
    default_model = DEFAULT_LLM_MODEL["openai"]

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

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        try:
            params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }

            overrides = get_openai_chat_overrides(model)
            if overrides["use_max_completion_tokens"]:
                if max_tokens:
                    params["max_completion_tokens"] = max_tokens
                if overrides["fixed_temperature"] is not None:
                    params["temperature"] = overrides["fixed_temperature"]
            elif max_tokens:
                params["max_tokens"] = max_tokens

            if seed is not None:
                params["seed"] = seed
            if stop:
                params["stop"] = stop

            response = await self.client.chat.completions.create(**params)

            content = response.choices[0].message.content or ""
            usage = response.usage

            latency = (time.perf_counter() - start_time) * 1000

            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens

            # Extract finish reason
            finish_reason = response.choices[0].finish_reason if response.choices else None

            # Convert usage to domain object
            usage_obj = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)

            cost = self.estimate_cost(usage_obj, model)

            return GenerationResult(
                text=content,
                model=model,
                provider=self.provider_name,
                usage=usage_obj,
                cost_estimate=cost,
                latency_ms=latency,
                finish_reason=finish_reason,
                metadata={"response_id": response.id},
            )

        except Exception as e:
            self._handle_error(e, model)

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
        stop: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ):
        """Stream text generation."""
        model = model or self.default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": prompt})

        try:
            params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            }

            # Handle model-specific parameter differences
            overrides = get_openai_chat_overrides(model)
            if overrides["use_max_completion_tokens"]:
                # These models require max_completion_tokens and fixed temperature
                if max_tokens:
                    params["max_completion_tokens"] = max_tokens
                if "max_tokens" in params:
                    del params["max_tokens"]

                if overrides["fixed_temperature"] is not None:
                    params["temperature"] = overrides["fixed_temperature"]
            elif max_tokens:
                params["max_tokens"] = max_tokens

            if seed is not None:
                params["seed"] = seed
            if stop:
                params["stop"] = stop

            # DIAGNOSTIC: Log the exact request being sent
            logger.warning(
                f"[DIAG] Calling OpenAI with: model={model}, msg_count={len(messages)}, temp={params.get('temperature')}, max_tokens={params.get('max_completion_tokens') or params.get('max_tokens')}"
            )
            if messages:
                logger.warning(
                    f"[DIAG] Last message role={messages[-1].get('role')}, content_len={len(str(messages[-1].get('content', '')))}"
                )

            stream = await self.client.chat.completions.create(**params)

            chunk_count = 0
            content_count = 0
            async for chunk in stream:
                chunk_count += 1
                if chunk.choices:
                    delta = chunk.choices[0].delta

                    # DIAGNOSTIC: Log first few chunks to understand structure
                    finish_reason = chunk.choices[0].finish_reason
                    if chunk_count <= 3 or finish_reason:
                        logger.warning(
                            f"[DIAG] Chunk {chunk_count}: delta={delta}, finish_reason={finish_reason}, delta.reasoning_content={getattr(delta, 'reasoning_content', None)}"
                        )

                    if delta.content:
                        content_count += 1
                        yield delta.content
                    elif getattr(delta, "reasoning_content", None):
                        # Some reasoning models use reasoning_content
                        content_count += 1
                        yield delta.reasoning_content
                    elif getattr(delta, "refusal", None):
                        yield f"[REFUSAL] {delta.refusal}"
                else:
                    # Keepalive or empty chunk
                    if chunk_count <= 3:
                        logger.warning(f"[DIAG] Empty chunk {chunk_count}: {chunk}")

            logger.warning(
                f"[DIAG] Stream finished: total_chunks={chunk_count}, content_chunks={content_count}"
            )

        except Exception as e:
            logger.error(f"[DIAG] Stream error for model {model}: {e}", exc_info=True)
            self._handle_error(e, model)

    def _handle_error(self, e: Exception, model: str) -> None:
        """Convert OpenAI exceptions to provider exceptions."""
        error_type = type(e).__name__

        if "RateLimitError" in error_type:
            # Check for hard quota limits vs transient rate limits
            error_str = str(e).lower()
            if "insufficient_quota" in error_str or "billing" in error_str:
                raise QuotaExceededError(
                    str(e),
                    provider=self.provider_name,
                    model=model,
                )

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
            # Map other errors
            raise ProviderUnavailableError(
                f"OpenAI error: {e}",
                provider=self.provider_name,
                model=model,
            )


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider."""

    provider_name = "openai"

    models = EMBEDDING_MODELS["openai"]
    default_model = DEFAULT_EMBEDDING_MODEL["openai"]

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
        if dimensions and embedding_supports_dimensions(model, provider=self.provider_name):
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
                cost_estimate=usage.input_tokens
                * self.models.get(model, {}).get("cost_per_1k", 0)
                / 1000,
            )

            return result

        except Exception as e:
            self._handle_error(e, model)

    def _handle_error(self, e: Exception, model: str) -> None:
        """Convert OpenAI exceptions to provider exceptions."""
        error_type = type(e).__name__

        if "RateLimitError" in error_type:
            # Check for hard quota limits vs transient rate limits
            error_str = str(e).lower()
            if "insufficient_quota" in error_str or "billing" in error_str:
                raise QuotaExceededError(
                    str(e),
                    provider=self.provider_name,
                    model=model,
                )

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
