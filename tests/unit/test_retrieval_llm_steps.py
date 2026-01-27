import pytest
from types import SimpleNamespace

from src.shared.kernel.runtime import configure_settings, _reset_for_tests


class DummySettings:
    default_llm_provider = "openai"
    default_llm_model = "gpt-4o-mini"
    default_llm_temperature = 0.0
    seed = 42
    db = SimpleNamespace(redis_url="redis://test")


@pytest.mark.asyncio
async def test_rewrite_step_resolves_custom_seed():
    from src.core.retrieval.application.query.rewriter import QueryRewriter

    configure_settings(DummySettings())

    class DummyProvider:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt: str, **kwargs):
            self.calls.append(kwargs)
            return "rewritten"

    class DummyFactory:
        def __init__(self, provider):
            self.provider = provider

        def get_llm_provider(self, **_kwargs):
            return self.provider

    provider = DummyProvider()
    factory = DummyFactory(provider)
    rewriter = QueryRewriter(provider_factory=factory)

    tenant_config = {
        "llm_steps": {
            "retrieval.query_rewrite": {
                "temperature": 0.4,
                "seed": 77,
                "provider": "openai",
                "model": "gpt-4o",
            }
        }
    }

    try:
        result = await rewriter.rewrite("hello", history="context", tenant_config=tenant_config)
        assert result == "rewritten"
        assert provider.calls
        assert provider.calls[0]["temperature"] == 0.4
        assert provider.calls[0]["seed"] == 77
    finally:
        _reset_for_tests()
