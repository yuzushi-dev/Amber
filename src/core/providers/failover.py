import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.providers.base import (
    BaseEmbeddingProvider,
    BaseLLMProvider,
    EmbeddingResult,
    GenerationResult,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from src.core.providers.resilience import CircuitBreaker

logger = logging.getLogger(__name__)

class FailoverLLMProvider(BaseLLMProvider):
    """
    LLM provider with automatic failover.

    Tries providers in order, falling back on errors.
    """

    provider_name = "failover"

    def __init__(
        self,
        providers: list[BaseLLMProvider],
        max_retries: int = 2,
    ):
        self.providers = providers
        self.max_retries = max_retries
        # Initialize circuit breaker for each provider
        self.circuits = {
            p.provider_name: CircuitBreaker(failure_threshold=5, recovery_timeout=300)
            for p in providers
        }

        if not providers:
            raise ValueError("At least one provider is required")

    def _validate_config(self) -> None:
        """No config to validate for aggregation."""
        pass

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
        """Generate with failover across providers."""
        last_error = None

        for provider in self.providers:
            circuit = self.circuits[provider.provider_name]

            # Check circuit state
            if not circuit.allow_request():
                logger.warning(f"Skipping provider {provider.provider_name} (Circuit {circuit.state.value})")
                continue

            try:
                logger.debug(f"Trying LLM provider: {provider.provider_name}")
                result = await provider.generate(
                    prompt=prompt,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=stop,
                    **kwargs,
                )

                # Success
                circuit.record_success()
                return result

            except RateLimitError as e:
                logger.warning(f"Rate limited by {provider.provider_name}: {e}")
                circuit.record_failure()
                last_error = e
                continue

            except ProviderUnavailableError as e:
                logger.warning(f"Provider {provider.provider_name} unavailable: {e}")
                circuit.record_failure()
                last_error = e
                continue

            except ProviderError as e:
                logger.error(f"Provider {provider.provider_name} error: {e}")
                last_error = e
                # Don't retry/record failure on auth/invalid request errors
                # (these are permanent config issues, not transient failures)
                if "Authentication" in type(e).__name__ or "Invalid" in type(e).__name__:
                    continue

                # Treat unknown provider errors as failures
                circuit.record_failure()
                break

        # All providers failed
        if not last_error:
             last_error = "All providers skipped or unavailable"

        raise ProviderUnavailableError(
            f"All providers failed. Last error: {last_error}",
            provider="failover",
        )

    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream with failover."""
        last_error = None

        for provider in self.providers:
            circuit = self.circuits[provider.provider_name]

            # Check circuit state
            if not circuit.allow_request():
                continue

            try:
                logger.debug(f"Trying streaming LLM provider: {provider.provider_name}")
                async for chunk in provider.generate_stream(
                    prompt=prompt,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ):
                    yield chunk

                # If we finished streaming without error, record success
                circuit.record_success()
                return

            except (RateLimitError, ProviderUnavailableError) as e:
                logger.warning(f"Provider {provider.provider_name} failed: {e}")
                circuit.record_failure()
                last_error = e
                continue

            except Exception as e:
                logger.error(f"Provider {provider.provider_name} streaming error: {e}")
                circuit.record_failure()
                last_error = e
                continue

        if not last_error:
             last_error = "All providers skipped or unavailable"

        raise ProviderUnavailableError(
            f"All providers failed for streaming. Last error: {last_error}",
            provider="failover",
        )


class FailoverEmbeddingProvider(BaseEmbeddingProvider):
    """Embedding provider with failover."""

    provider_name = "failover"

    def __init__(self, providers: list[BaseEmbeddingProvider]):
        self.providers = providers

        if not providers:
            raise ValueError("At least one provider is required")

    def _validate_config(self):
        """No config to validate for aggregation."""
        pass

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        dimensions: int | None = None,
        **kwargs: Any,
    ) -> EmbeddingResult:
        """Embed with failover across providers."""
        last_error = None

        for provider in self.providers:
            try:
                logger.debug(f"Trying embedding provider: {provider.provider_name}")
                return await provider.embed(
                    texts=texts,
                    model=model,
                    dimensions=dimensions,
                    **kwargs,
                )

            except (RateLimitError, ProviderUnavailableError) as e:
                logger.warning(f"Provider {provider.provider_name} failed: {e}")
                last_error = e
                continue

        raise ProviderUnavailableError(
            f"All embedding providers failed. Last error: {last_error}",
            provider="failover",
        )
