from types import SimpleNamespace

import pytest

from src.core.generation.application.generation_service import GenerationConfig, GenerationService
from src.shared.kernel.runtime import _reset_for_tests, configure_settings
from src.shared.model_registry import DEFAULT_LLM_MODEL


class DummySettings:
    default_llm_provider = "openai"
    default_llm_model = DEFAULT_LLM_MODEL["openai"]
    default_llm_temperature = 0.0
    seed = 42
    db = SimpleNamespace(redis_url="redis://test")


@pytest.fixture(autouse=True)
def configure_runtime_settings():
    configure_settings(DummySettings())
    yield
    _reset_for_tests()


class DummyProvider:
    provider_name = "dummy"
    model_name = "dummy-model"

    async def generate_stream(self, *args, **kwargs):
        yield "Hello"


@pytest.mark.asyncio
async def test_stream_done_includes_provider():
    service = GenerationService(
        llm_provider=DummyProvider(),
        config=GenerationConfig(max_tokens=8),
    )
    events = []
    async for event in service.generate_stream(
        query="hi",
        candidates=[{"content": "ctx"}],
        options={"tenant_id": None, "user_id": None},
    ):
        events.append(event)

    done = next(e for e in events if e.get("event") == "done")
    assert done["data"]["provider"] == "dummy"
    assert done["data"]["model"] == "dummy-model"
