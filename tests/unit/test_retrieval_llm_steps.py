from types import SimpleNamespace

import pytest

from src.shared.kernel.runtime import _reset_for_tests, configure_settings
from src.shared.model_registry import DEFAULT_LLM_MODEL, LLM_MODELS


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OPENAI_DEFAULT = DEFAULT_LLM_MODEL["openai"]
OPENAI_ALT = _first_other(LLM_MODELS["openai"], OPENAI_DEFAULT)


class DummySettings:
    default_llm_provider = "openai"
    default_llm_model = OPENAI_DEFAULT
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
                "model": OPENAI_ALT,
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
