from src.core.generation.application.llm_steps import resolve_llm_step_config


class DummySettings:
    default_llm_provider = "openai"
    default_llm_model = "gpt-4o-mini"
    default_llm_temperature = 0.0
    seed = 42


def test_resolve_llm_step_config_fallbacks():
    tenant_config = {
        "llm_provider": "anthropic",
        "llm_model": "claude-3-5-haiku-20241022",
        "llm_steps": {
            "ingestion.graph_extraction": {
                "temperature": 0.2,
                "seed": 123
            }
        }
    }

    cfg = resolve_llm_step_config(
        tenant_config=tenant_config,
        step_id="ingestion.graph_extraction",
        settings=DummySettings(),
    )

    assert cfg.temperature == 0.2
    assert cfg.seed == 123
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-3-5-haiku-20241022"


def test_resolve_llm_step_config_generation_model_fallback():
    tenant_config = {"generation_model": "gpt-4.1-mini"}

    cfg = resolve_llm_step_config(
        tenant_config=tenant_config,
        step_id="ingestion.graph_extraction",
        settings=DummySettings(),
    )

    assert cfg.model == "gpt-4.1-mini"
