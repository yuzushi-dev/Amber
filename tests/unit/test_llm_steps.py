from src.core.generation.application.llm_steps import resolve_llm_step_config
from src.shared.model_registry import DEFAULT_LLM_MODEL, LLM_MODELS


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OPENAI_DEFAULT = DEFAULT_LLM_MODEL["openai"]
OPENAI_ALT = _first_other(LLM_MODELS["openai"], OPENAI_DEFAULT)
ANTHROPIC_DEFAULT = DEFAULT_LLM_MODEL["anthropic"]


class DummySettings:
    default_llm_provider = "openai"
    default_llm_model = OPENAI_DEFAULT
    default_llm_temperature = 0.0
    seed = 42


def test_resolve_llm_step_config_fallbacks():
    tenant_config = {
        "llm_provider": "anthropic",
        "llm_model": ANTHROPIC_DEFAULT,
        "llm_steps": {"ingestion.graph_extraction": {"temperature": 0.2, "seed": 123}},
    }

    cfg = resolve_llm_step_config(
        tenant_config=tenant_config,
        step_id="ingestion.graph_extraction",
        settings=DummySettings(),
    )

    assert cfg.temperature == 0.2
    assert cfg.seed == 123
    assert cfg.provider == "anthropic"
    assert cfg.model == ANTHROPIC_DEFAULT


def test_resolve_llm_step_config_generation_model_fallback():
    tenant_config = {"generation_model": OPENAI_ALT}

    cfg = resolve_llm_step_config(
        tenant_config=tenant_config,
        step_id="ingestion.graph_extraction",
        settings=DummySettings(),
    )

    assert cfg.model == OPENAI_ALT
