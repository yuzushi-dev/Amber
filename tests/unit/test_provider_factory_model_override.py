from src.core.generation.infrastructure.providers.factory import ProviderFactory
from src.shared.model_registry import DEFAULT_LLM_MODEL, LLM_MODELS


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OPENAI_DEFAULT = DEFAULT_LLM_MODEL["openai"]
OPENAI_ALT = _first_other(LLM_MODELS["openai"], OPENAI_DEFAULT)


def test_get_llm_provider_with_model_override():
    factory = ProviderFactory(
        openai_api_key="test",
        anthropic_api_key=None,
        ollama_base_url=None,
        default_llm_provider=None,
        default_llm_model=None,
    )

    llm = factory.get_llm_provider(provider_name="openai", model=OPENAI_ALT)

    assert llm.default_model == OPENAI_ALT
