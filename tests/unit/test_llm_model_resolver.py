from src.core.generation.application.llm_model_resolver import resolve_tenant_llm_model


class DummySettings:
    default_llm_model = "gpt-4o-mini"


def test_llm_model_precedence():
    tenant_config = {"llm_model": "gpt-4.1-mini", "generation_model": "gpt-4o-mini"}
    model, source = resolve_tenant_llm_model(tenant_config, DummySettings(), context="test")
    assert model == "gpt-4.1-mini"
    assert source == "llm_model"


def test_generation_model_fallback():
    tenant_config = {"generation_model": "gpt-4o-mini"}
    model, source = resolve_tenant_llm_model(tenant_config, DummySettings(), context="test")
    assert model == "gpt-4o-mini"
    assert source == "generation_model"
