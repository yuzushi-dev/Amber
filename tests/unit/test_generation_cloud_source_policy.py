from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.generation.application.generation_service import GenerationService
from src.core.generation.infrastructure.providers.factory import ProviderFactory
from src.shared.model_registry import LLM_MODEL_TO_PROVIDERS, resolve_provider_for_model


MODEL = "gemma4:31b-cloud"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", [None, "editions", "factory", "credentials"])
async def test_cloud_override_and_commercial_prompt(monkeypatch, stream, failure):
    settings = SimpleNamespace(
        default_llm_provider="ollama", default_llm_model="glm-5.2:cloud",
        default_llm_temperature=0.0, seed=42,
    )
    monkeypatch.setattr("src.shared.kernel.runtime.get_settings", lambda: settings)
    rules = SimpleNamespace(get_active_rules=AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "src.core.admin_ops.application.rules_service.get_rules_service", lambda: rules
    )
    repository = SimpleNamespace(get_editions_by_ids=AsyncMock(return_value={
        "commercial": "commercial", "ce": "ce", "unknown": "unknown",
    }))
    if failure == "editions":
        repository.get_editions_by_ids.side_effect = RuntimeError("edition lookup unavailable")
    llm = MagicMock(model_name=MODEL, provider_name="ollama_cloud")
    llm.generate = AsyncMock(return_value=SimpleNamespace(
        text="Grounded response.", model=MODEL, provider="ollama_cloud",
        usage=SimpleNamespace(total_tokens=3, input_tokens=2, output_tokens=1),
        cost_estimate=0, latency_ms=1,
    ))

    async def tokens(**kwargs):
        yield "Grounded response."

    llm.generate_stream.side_effect = tokens
    service = GenerationService(llm_provider=llm, document_repository=repository)
    service._get_document_titles = AsyncMock(return_value={})
    factory = MagicMock()
    factory.get_llm_provider.return_value = llm
    if failure == "credentials":
        factory.get_llm_provider.side_effect = RuntimeError("cloud credentials unavailable")
    service.factory = None if failure == "factory" else factory
    candidates = [
        {"document_id": name, "chunk_id": name, "content": name + "_evidence", "score": 1}
        for name in ("commercial", "ce", "unknown", "unclassified")
    ]

    async def run():
        kwargs = dict(query="How do I hide View Mail?", candidates=candidates,
                      options={"model": MODEL, "tenant_id": "default"})
        if stream:
            return [event async for event in service.generate_stream(**kwargs)]
        return await service.generate(**kwargs)

    if failure:
        with pytest.raises(RuntimeError):
            await run()
        llm.generate.assert_not_called()
        llm.generate_stream.assert_not_called()
        return

    await run()
    factory.get_llm_provider.assert_called_once_with(
        provider_name="ollama_cloud", model=MODEL, tier=service.config.tier,
        with_failover=False,
    )
    call = llm.generate_stream.call_args if stream else llm.generate.call_args
    assert call.kwargs["model"] == MODEL
    assert "commercial_evidence" in call.kwargs["prompt"]
    for forbidden in ("ce_evidence", "unknown_evidence", "unclassified_evidence"):
        assert forbidden not in call.kwargs["prompt"]


def test_cloud_model_without_credentials_cannot_fall_back():
    owner = resolve_provider_for_model(MODEL, LLM_MODEL_TO_PROVIDERS, kind="llm")
    assert owner == "ollama_cloud"
    factory = ProviderFactory(default_llm_provider="ollama", ollama_cloud_api_keys=[])
    with pytest.raises(Exception, match="OLLAMA_CLOUD_API_KEYS is empty"):
        factory.get_llm_provider(provider_name=owner, model=MODEL, with_failover=False)
