"""Guard: every provider default model must exist in the catalog.

Catches the class of bug where DEFAULT_LLM_MODEL points at a model that was
removed/renamed in LLM_MODELS (drift between the default and the catalog).
"""

from src.shared.model_registry import DEFAULT_LLM_MODEL, LLM_MODELS


def test_defaults_exist_in_catalog():
    for provider, model in DEFAULT_LLM_MODEL.items():
        assert provider in LLM_MODELS, f"provider {provider!r} missing from LLM_MODELS"
        assert model in LLM_MODELS[provider], (
            f"default model {model!r} for provider {provider!r} is not in the catalog"
        )


def test_ollama_cloud_default_is_current():
    # gemma3:27b was retired upstream (410 Gone on Ollama Cloud) — must not return.
    assert DEFAULT_LLM_MODEL["ollama_cloud"] != "gemma3:27b"


if __name__ == "__main__":
    test_defaults_exist_in_catalog()
    test_ollama_cloud_default_is_current()
    print("ok")
