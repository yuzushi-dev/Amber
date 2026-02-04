from src.core.generation.application.llm_model_resolver import resolve_tenant_llm_model
from src.shared.model_registry import DEFAULT_LLM_MODEL, LLM_MODELS


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OPENAI_DEFAULT = DEFAULT_LLM_MODEL["openai"]
OPENAI_ALT = _first_other(LLM_MODELS["openai"], OPENAI_DEFAULT)


class DummySettings:
    default_llm_model = OPENAI_DEFAULT


def test_llm_model_precedence():
    tenant_config = {"llm_model": OPENAI_DEFAULT, "generation_model": OPENAI_ALT}
    model, source = resolve_tenant_llm_model(tenant_config, DummySettings(), context="test")
    assert model == OPENAI_DEFAULT
    assert source == "llm_model"


def test_generation_model_fallback():
    tenant_config = {"generation_model": OPENAI_ALT}
    model, source = resolve_tenant_llm_model(tenant_config, DummySettings(), context="test")
    assert model == OPENAI_ALT
    assert source == "generation_model"
