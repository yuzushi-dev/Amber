from src.shared.model_registry import DEFAULT_LLM_MODEL, DEFAULT_EMBEDDING_MODEL


def test_registry_defaults_exist():
    assert DEFAULT_LLM_MODEL["openai"]
    assert DEFAULT_EMBEDDING_MODEL["openai"]
