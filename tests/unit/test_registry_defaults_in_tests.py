from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, DEFAULT_LLM_MODEL


def test_registry_defaults_exist():
    assert DEFAULT_LLM_MODEL["openai"]
    assert DEFAULT_EMBEDDING_MODEL["openai"]
