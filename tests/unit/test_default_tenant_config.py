from src.core.admin_ops.application.api_key_service import _default_tenant_config


def test_default_tenant_config_includes_llm_model():
    config = _default_tenant_config()

    assert config["embedding_model"] == "text-embedding-3-small"
    assert config["llm_model"] == "gpt-4o-mini"
    assert config["generation_model"] == "gpt-4o-mini"
