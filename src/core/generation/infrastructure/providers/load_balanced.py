import logging
import random
from collections.abc import AsyncIterator
from typing import Any

from src.core.generation.infrastructure.providers.base import (
    BaseLLMProvider,
    GenerationResult,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from src.core.generation.infrastructure.providers.resilience import CircuitBreaker

logger = logging.getLogger(__name__)

class LoadBalancedLLMProvider(BaseLLMProvider):
    """
    LLM provider that distributes requests across multiple sub-providers.
    Uses a random selection strategy to balance load.
    """

    provider_name = "load_balanced"

    def __init__(
        self,
        providers: list[BaseLLMProvider],
    ):
        self.providers = providers
        # Initialize circuit breaker for each provider
        self.circuits = {
            p.provider_name: CircuitBreaker(failure_threshold=5, recovery_timeout=300)
            for p in providers
        }

        if not providers:
            raise ValueError("At least one provider is required")

    @property
    def model_name(self) -> str:
        return self.providers[0].model_name

    def _validate_config(self) -> None:
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
        # Shuffle providers to try them in random order
        pool = list(self.providers)
        random.shuffle(pool)

        last_error = None
        for provider in pool:
            circuit = self.circuits[provider.provider_name]

            if not circuit.allow_request():
                continue

            try:
                logger.info(f"[LoadBalance] Trying LLM provider: {provider.provider_name}")
                result = await provider.generate(
                    prompt=prompt,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=stop,
                    **kwargs,
                )
                circuit.record_success()
                return result

            except (RateLimitError, ProviderUnavailableError) as e:
                logger.warning(f"Provider {provider.provider_name} busy or unavailable: {e}")
                circuit.record_failure()
                last_error = e
                continue

            except ProviderError as e:
                logger.error(f"Provider {provider.provider_name} error: {e}")
                last_error = e
                # Don't record failure on auth errors, but move to next
                if "Authentication" not in type(e).__name__:
                    circuit.record_failure()
                continue

        raise ProviderUnavailableError(
            f"All load-balanced providers failed. Last error: {last_error}",
            provider="load_balanced",
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = "auto",
        **kwargs: Any,
    ) -> Any:
        """Chat completion with load-balanced failover."""
        pool = list(self.providers)
        random.shuffle(pool)

        last_error = None
        for provider in pool:
            circuit = self.circuits[provider.provider_name]

            if not circuit.allow_request():
                continue

            try:
                logger.info(f"[LoadBalance] Trying chat provider: {provider.provider_name}")
                result = await provider.chat(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    **kwargs,
                )
                circuit.record_success()
                return result

            except (RateLimitError, ProviderUnavailableError) as e:
                logger.warning(f"Provider {provider.provider_name} busy or unavailable: {e}")
                circuit.record_failure()
                last_error = e
                continue

            except ProviderError as e:
                logger.error(f"Provider {provider.provider_name} error: {e}")
                last_error = e
                if "Authentication" not in type(e).__name__:
                    circuit.record_failure()
                continue

        raise ProviderUnavailableError(
            f"All load-balanced providers failed for chat. Last error: {last_error}",
            provider="load_balanced",
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
        pool = list(self.providers)
        random.shuffle(pool)

        last_error = None
        for provider in pool:
            circuit = self.circuits[provider.provider_name]

            if not circuit.allow_request():
                continue

            try:
                logger.info(f"[LoadBalance] Trying streaming LLM provider: {provider.provider_name}")
                async for chunk in provider.generate_stream(
                    prompt=prompt,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ):
                    yield chunk
                circuit.record_success()
                return

            except (RateLimitError, ProviderUnavailableError) as e:
                circuit.record_failure()
                last_error = e
                continue
            except Exception as e:
                circuit.record_failure()
                last_error = e
                continue

        raise ProviderUnavailableError(
            f"All load-balanced providers failed for streaming. Last error: {last_error}",
            provider="load_balanced",
        )
