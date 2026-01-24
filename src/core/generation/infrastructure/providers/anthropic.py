"""
Anthropic Provider
==================

LLM provider implementation for Anthropic Claude models.
"""

import logging
import time
from typing import Any

from src.core.generation.infrastructure.providers.base import (
    AuthenticationError,
    BaseLLMProvider,
    GenerationResult,
    InvalidRequestError,
    ProviderConfig,
    ProviderTier,
    ProviderUnavailableError,
    RateLimitError,
    TokenUsage,
)
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


def _get_anthropic_client(api_key: str):
    """Get Anthropic client."""
    try:
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=api_key)
    except ImportError as e:
        raise ImportError("anthropic package is required. Install with: pip install anthropic>=0.18.0") from e


class AnthropicLLMProvider(BaseLLMProvider):
    """Anthropic Claude LLM provider."""

    provider_name = "anthropic"

    models = {
        "claude-sonnet-4-20250514": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.003,  # $3/1M tokens
            "output_cost_per_1k": 0.015,  # $15/1M tokens
            "context_window": 200000,
            "description": "Claude Sonnet 4 - Best balance",
        },
        "claude-3-5-sonnet-20241022": {
            "tier": ProviderTier.STANDARD,
            "input_cost_per_1k": 0.003,
            "output_cost_per_1k": 0.015,
            "context_window": 200000,
            "description": "Claude 3.5 Sonnet",
        },
        "claude-3-5-haiku-20241022": {
            "tier": ProviderTier.ECONOMY,
            "input_cost_per_1k": 0.0008,  # $0.80/1M tokens
            "output_cost_per_1k": 0.004,  # $4/1M tokens
            "context_window": 200000,
            "description": "Claude 3.5 Haiku - Fast and affordable",
        },
        "claude-3-opus-20240229": {
            "tier": ProviderTier.PREMIUM,
            "input_cost_per_1k": 0.015,  # $15/1M tokens
            "output_cost_per_1k": 0.075,  # $75/1M tokens
            "context_window": 200000,
            "description": "Claude 3 Opus - Most capable",
        },
    }

    default_model = "claude-3-5-haiku-20241022"

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
            self._client = _get_anthropic_client(self.config.api_key)
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
        """Generate text using Anthropic Messages API."""
        model = model or self.default_model
        start_time = time.perf_counter()

        # Default max tokens (Anthropic requires explicit max_tokens)
        max_tokens = max_tokens or 4096

        try:
            # Build request
            request_params: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            if system_prompt:
                request_params["system"] = system_prompt

            if stop:
                request_params["stop_sequences"] = stop

            response = await self.client.messages.create(**request_params)

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Extract usage
            usage = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            # Extract text from content blocks
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            result = GenerationResult(
                text=text,
                model=model,
                provider=self.provider_name,
                usage=usage,
                finish_reason=response.stop_reason,
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
        max_tokens = max_tokens or 4096

        try:
            request_params: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            if system_prompt:
                request_params["system"] = system_prompt

            async with self.client.messages.stream(**request_params) as stream:
                async for text in stream.text_stream:
                    yield text

        except Exception as e:
            self._handle_error(e, model)

    def _handle_error(self, e: Exception, model: str) -> None:
        """Convert Anthropic exceptions to provider exceptions."""
        error_type = type(e).__name__
        error_msg = str(e)

        if "RateLimitError" in error_type or "rate_limit" in error_msg.lower():
            raise RateLimitError(
                str(e),
                provider=self.provider_name,
                model=model,
                retry_after=60.0,
            )
        elif "AuthenticationError" in error_type or "authentication" in error_msg.lower():
            raise AuthenticationError(
                str(e),
                provider=self.provider_name,
                model=model,
            )
        elif "BadRequestError" in error_type or "invalid" in error_msg.lower():
            raise InvalidRequestError(
                str(e),
                provider=self.provider_name,
                model=model,
            )
        elif "APIConnectionError" in error_type or "connection" in error_msg.lower():
            raise ProviderUnavailableError(
                str(e),
                provider=self.provider_name,
                model=model,
            )
        else:
            raise ProviderUnavailableError(
                f"Unexpected error: {e}",
                provider=self.provider_name,
                model=model,
            )
