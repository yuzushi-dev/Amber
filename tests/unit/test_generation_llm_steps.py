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
async def test_memory_fact_extraction_uses_step_config(monkeypatch):
    from src.core.generation.application.memory.extractor import MemoryExtractor

    configure_settings(DummySettings())

    class DummyProvider:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt: str, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text="NO_FACTS")

    class DummyFactory:
        def __init__(self, provider):
            self.provider = provider

        def get_llm_provider(self, **_kwargs):
            return self.provider

    provider = DummyProvider()
    factory = DummyFactory(provider)

    monkeypatch.setattr(
        "src.core.generation.domain.ports.provider_factory.get_provider_factory",
        lambda: factory,
    )

    extractor = MemoryExtractor()

    tenant_config = {
        "llm_steps": {
            "memory.fact_extraction": {
                "temperature": 0.0,
                "seed": 123,
                "provider": "openai",
                "model": "gpt-4o",
            }
        }
    }

    try:
        result = await extractor.extract_and_save_facts(
            tenant_id="default",
            user_id="user",
            text="Some user fact",
            tenant_config=tenant_config,
        )
        assert result == []
        assert provider.calls
        assert provider.calls[0]["temperature"] == 0.0
        assert provider.calls[0]["seed"] == 123
    finally:
        _reset_for_tests()
