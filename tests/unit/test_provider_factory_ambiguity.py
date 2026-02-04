import pytest

from src.core.generation.domain.provider_models import ConfigurationError
from src.core.generation.infrastructure.providers import factory as factory_mod
from src.core.generation.infrastructure.providers.factory import ProviderFactory
from src.shared.model_registry import DEFAULT_LLM_MODEL


AMBIGUOUS_MODEL = DEFAULT_LLM_MODEL["openai"]


def test_model_only_ambiguous_raises(monkeypatch):
    monkeypatch.setitem(
        factory_mod.LLM_MODEL_TO_PROVIDERS,
        AMBIGUOUS_MODEL,
        {"openai", "ollama"},
    )
    factory = ProviderFactory(
        openai_api_key="sk-...",
        anthropic_api_key="sk-...",
        ollama_base_url="http://ollama",
    )
    with pytest.raises(ConfigurationError):
        factory.get_llm_provider(model=AMBIGUOUS_MODEL)
