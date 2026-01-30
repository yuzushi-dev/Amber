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
    QuotaExceededError,
    RateLimitError,
    TokenUsage,
)
from src.shared.kernel.observability import trace_span
from src.shared.context import get_current_tenant, get_request_id

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
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): pass
        
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
            _openai_client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url
            )
            
        return _openai_client
    except ImportError as e:
        raise ImportError("openai package is required. Install with: pip install openai>=1.10.0") from e


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI LLM provider for GPT models."""
    
    provider_name = "openai"
    
    # Models supported by this provider for validation
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
        "gpt-5-mini": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00015,  # Placeholder
            "output_cost_per_1k": 0.0006,  # Placeholder
            "context_window": 128000,
            "description": "Next-gen compact model",
        },
        "gpt-5-nano": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.00010,  # Placeholder
            "output_cost_per_1k": 0.0004,  # Placeholder
            "context_window": 128000,
            "description": "Ultra-efficient compact model",
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

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})

        # Cost estimation logic (simplified)
        cost_per_1k_input = 0.00015 # gpt-4o-mini approx
        cost_per_1k_output = 0.0006
        
        if "gpt-4o" in model and "mini" not in model:
            cost_per_1k_input = 0.005
            cost_per_1k_output = 0.015

        try:
            params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }

            if model in ["o1", "o3-mini", "gpt-5-nano", "gpt-5-mini"]:
                if max_tokens:
                     params["max_completion_tokens"] = max_tokens
                params["temperature"] = 1.0
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
            cost = (input_tokens / 1000 * cost_per_1k_input) + (output_tokens / 1000 * cost_per_1k_output)

            # Extract finish reason
            finish_reason = response.choices[0].finish_reason if response.choices else None

            # Convert usage to domain object
            usage_obj = TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=usage.total_tokens
            )

            return GenerationResult(
                text=content,
                model=model,
                provider=self.provider_name,
                usage=usage_obj,
                cost_estimate=cost,
                latency_ms=latency,
                finish_reason=finish_reason,
                metadata={"response_id": response.id}
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
            if model in ["o1", "o3-mini", "gpt-5-nano", "gpt-5-mini"]:
                # These models require max_completion_tokens and fixed temperature
                if max_tokens:
                     params["max_completion_tokens"] = max_tokens
                if "max_tokens" in params:
                     del params["max_tokens"]
                
                params["temperature"] = 1.0
            elif max_tokens:
                params["max_tokens"] = max_tokens
                    
            if seed is not None:
                params["seed"] = seed
            if stop:
                params["stop"] = stop

            stream = await self.client.chat.completions.create(**params)
            
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    
                    if delta.content:
                        yield delta.content
                    elif getattr(delta, "refusal", None):
                        yield f"[REFUSAL] {delta.refusal}"
                else:
                    # Keepalive or empty chunk
                    pass

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
             # Map other errors
             raise ProviderUnavailableError(
                f"OpenAI error: {e}",
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
                total_tokens=response.usage.total_tokens if response.usage else 0,
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
