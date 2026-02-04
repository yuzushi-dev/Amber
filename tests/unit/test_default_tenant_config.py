from src.core.admin_ops.application.api_key_service import _default_tenant_config
from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, DEFAULT_LLM_MODEL


def test_default_tenant_config_includes_llm_model():
    config = _default_tenant_config()

    assert config["embedding_model"] == DEFAULT_EMBEDDING_MODEL["openai"]
    assert config["llm_model"] == DEFAULT_LLM_MODEL["openai"]
    assert config["generation_model"] == DEFAULT_LLM_MODEL["openai"]
