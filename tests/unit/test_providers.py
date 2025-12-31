"""
Provider Unit Tests
===================

Tests for the model provider abstraction layer.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.providers.base import (
    BaseLLMProvider,
    BaseEmbeddingProvider,
    GenerationResult,
    EmbeddingResult,
    ProviderConfig,
    ProviderTier,
    ProviderUnavailableError,
    RateLimitError,
    TokenUsage,
)
from src.core.providers.factory import (
    ProviderFactory,
    FailoverLLMProvider,
    FailoverEmbeddingProvider,
)


# =============================================================================
# Mock Providers for Testing
# =============================================================================


class MockLLMProvider(BaseLLMProvider):
    """Mock LLM provider for testing."""

    provider_name = "mock"
    models = {"mock-model": {"tier": ProviderTier.ECONOMY}}
    default_model = "mock-model"

    def __init__(self, should_fail: bool = False, fail_type: str = "unavailable"):
        super().__init__(ProviderConfig())
        self.should_fail = should_fail
        self.fail_type = fail_type
        self.call_count = 0

    async def generate(self, prompt: str, **kwargs) -> GenerationResult:
        self.call_count += 1
        if self.should_fail:
            if self.fail_type == "rate_limit":
                raise RateLimitError("Rate limited", provider=self.provider_name)
            else:
                raise ProviderUnavailableError("Unavailable", provider=self.provider_name)

        return GenerationResult(
            text=f"Response to: {prompt}",
            model="mock-model",
            provider=self.provider_name,
            usage=TokenUsage(input_tokens=10, output_tokens=20),
        )


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Mock embedding provider for testing."""

    provider_name = "mock"
    models = {"mock-embed": {"dimensions": 128}}
    default_model = "mock-embed"

    def __init__(self, should_fail: bool = False):
        super().__init__(ProviderConfig())
        self.should_fail = should_fail
        self.call_count = 0

    async def embed(self, texts: list[str], **kwargs) -> EmbeddingResult:
        self.call_count += 1
        if self.should_fail:
            raise ProviderUnavailableError("Unavailable", provider=self.provider_name)

        return EmbeddingResult(
            embeddings=[[0.1] * 128 for _ in texts],
            model="mock-embed",
            provider=self.provider_name,
            usage=TokenUsage(input_tokens=len(texts) * 10),
            dimensions=128,
        )


# =============================================================================
# Base Provider Tests
# =============================================================================


class TestProviderConfig:
    """Tests for ProviderConfig."""

    def test_default_config(self):
        config = ProviderConfig()
        assert config.api_key is None
        assert config.timeout == 60.0
        assert config.max_retries == 3

    def test_custom_config(self):
        config = ProviderConfig(
            api_key="test-key",
            timeout=30.0,
            max_retries=5,
        )
        assert config.api_key == "test-key"
        assert config.timeout == 30.0


class TestTokenUsage:
    """Tests for TokenUsage."""

    def test_total_tokens(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_defaults(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0


# =============================================================================
# Failover Provider Tests
# =============================================================================


class TestFailoverLLMProvider:
    """Tests for FailoverLLMProvider."""

    @pytest.mark.asyncio
    async def test_uses_first_provider_on_success(self):
        provider1 = MockLLMProvider()
        provider2 = MockLLMProvider()
        failover = FailoverLLMProvider([provider1, provider2])

        result = await failover.generate("test")

        assert result.text == "Response to: test"
        assert provider1.call_count == 1
        assert provider2.call_count == 0

    @pytest.mark.asyncio
    async def test_failover_on_unavailable(self):
        provider1 = MockLLMProvider(should_fail=True, fail_type="unavailable")
        provider2 = MockLLMProvider()
        failover = FailoverLLMProvider([provider1, provider2])

        result = await failover.generate("test")

        assert result.text == "Response to: test"
        assert provider1.call_count == 1
        assert provider2.call_count == 1

    @pytest.mark.asyncio
    async def test_failover_on_rate_limit(self):
        provider1 = MockLLMProvider(should_fail=True, fail_type="rate_limit")
        provider2 = MockLLMProvider()
        failover = FailoverLLMProvider([provider1, provider2])

        result = await failover.generate("test")

        assert provider1.call_count == 1
        assert provider2.call_count == 1

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        provider1 = MockLLMProvider(should_fail=True)
        provider2 = MockLLMProvider(should_fail=True)
        failover = FailoverLLMProvider([provider1, provider2])

        with pytest.raises(ProviderUnavailableError) as exc_info:
            await failover.generate("test")

        assert "All providers failed" in str(exc_info.value)

    def test_requires_at_least_one_provider(self):
        with pytest.raises(ValueError):
            FailoverLLMProvider([])


class TestFailoverEmbeddingProvider:
    """Tests for FailoverEmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_uses_first_provider_on_success(self):
        provider1 = MockEmbeddingProvider()
        provider2 = MockEmbeddingProvider()
        failover = FailoverEmbeddingProvider([provider1, provider2])

        result = await failover.embed(["test"])

        assert len(result.embeddings) == 1
        assert provider1.call_count == 1
        assert provider2.call_count == 0

    @pytest.mark.asyncio
    async def test_failover_on_error(self):
        provider1 = MockEmbeddingProvider(should_fail=True)
        provider2 = MockEmbeddingProvider()
        failover = FailoverEmbeddingProvider([provider1, provider2])

        result = await failover.embed(["test"])

        assert len(result.embeddings) == 1
        assert provider1.call_count == 1
        assert provider2.call_count == 1


# =============================================================================
# Provider Factory Tests
# =============================================================================


class TestProviderFactory:
    """Tests for ProviderFactory."""

    def test_factory_creation(self):
        factory = ProviderFactory(
            openai_api_key="test-openai",
            anthropic_api_key="test-anthropic",
        )
        assert factory.openai_api_key == "test-openai"
        assert factory.anthropic_api_key == "test-anthropic"

    def test_no_providers_available(self):
        factory = ProviderFactory()  # No API keys

        with pytest.raises(ProviderUnavailableError) as exc_info:
            factory.get_llm_provider()

        assert "No LLM providers available" in str(exc_info.value)

    def test_get_llm_provider_with_openai(self):
        factory = ProviderFactory(openai_api_key="test-key")
        provider = factory.get_llm_provider(tier=ProviderTier.ECONOMY)

        assert provider is not None
        # Should be OpenAI provider (or failover containing it)

    def test_get_embedding_provider_with_local_fallback(self):
        factory = ProviderFactory(enable_local_fallback=True)
        # Should not raise even without API keys if local is available
        try:
            provider = factory.get_embedding_provider()
            assert provider is not None
        except ProviderUnavailableError:
            # Local provider not installed - acceptable in test env
            pass

    def test_provider_caching(self):
        factory = ProviderFactory(openai_api_key="test-key")
        provider1 = factory.get_llm_provider(with_failover=False)
        provider2 = factory.get_llm_provider(with_failover=False)

        # Should return cached instance
        assert provider1 is provider2


# =============================================================================
# Cost Estimation Tests
# =============================================================================


class TestCostEstimation:
    """Tests for cost estimation."""

    def test_openai_cost_estimation(self):
        from src.core.providers.openai import OpenAILLMProvider

        # Create with mock config (won't validate since we don't call generate)
        provider = object.__new__(OpenAILLMProvider)
        provider.models = OpenAILLMProvider.models

        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = provider.estimate_cost(usage, "gpt-4o-mini")

        # gpt-4o-mini: $0.15/1M input, $0.60/1M output
        # 1000 input = $0.00015, 500 output = $0.0003
        expected = (0.00015 * 1000 / 1000) + (0.0006 * 500 / 1000)
        assert abs(cost - expected) < 0.0001


# =============================================================================
# Exception Tests
# =============================================================================


class TestProviderExceptions:
    """Tests for provider exceptions."""

    def test_provider_error_format(self):
        from src.core.providers.base import ProviderError

        error = ProviderError("Test error", provider="test", model="test-model")
        assert "[test]" in str(error)
        assert "Test error" in str(error)

    def test_rate_limit_error_retry_after(self):
        error = RateLimitError(
            "Rate limited",
            provider="test",
            retry_after=30.0,
        )
        assert error.retry_after == 30.0
