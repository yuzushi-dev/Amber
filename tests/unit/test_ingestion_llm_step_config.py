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
async def test_graph_extraction_uses_step_temperature(monkeypatch):
    from src.core.ingestion.infrastructure.extraction.graph_extractor import GraphExtractor

    configure_settings(DummySettings())

    class DummyProvider:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt: str, temperature: float = 0.7, seed=None, **kwargs):
            self.calls.append({"temperature": temperature, "seed": seed})
            return SimpleNamespace(
                text="",
                usage=SimpleNamespace(total_tokens=0, input_tokens=0, output_tokens=0),
                cost_estimate=0.0,
                model="dummy",
                provider="dummy",
            )

    provider = DummyProvider()

    monkeypatch.setattr(
        "src.core.ingestion.infrastructure.extraction.graph_extractor.get_llm_provider",
        lambda *args, **kwargs: provider,
    )

    extractor = GraphExtractor(use_gleaning=False)
    extractor.parser = SimpleNamespace(parse=lambda _text: SimpleNamespace(entities=[], relationships=[]))

    tenant_config = {
        "llm_steps": {
            "ingestion.graph_extraction": {
                "temperature": 0.2,
                "seed": 99,
                "provider": "openai",
                "model": "gpt-4o",
            }
        }
    }

    try:
        await extractor.extract("sample", chunk_id="c1", track_usage=False, tenant_config=tenant_config)

        assert provider.calls
        assert provider.calls[0]["temperature"] == 0.2
        assert provider.calls[0]["seed"] == 99
    finally:
        _reset_for_tests()
