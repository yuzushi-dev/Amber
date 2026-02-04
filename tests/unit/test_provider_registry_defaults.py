from src.shared.model_registry import DEFAULT_LLM_MODEL, DEFAULT_EMBEDDING_MODEL
from src.core.generation.infrastructure.providers.openai import OpenAILLMProvider, OpenAIEmbeddingProvider


def test_openai_defaults_match_registry():
    assert OpenAILLMProvider.default_model == DEFAULT_LLM_MODEL["openai"]
    assert OpenAIEmbeddingProvider.default_model == DEFAULT_EMBEDDING_MODEL["openai"]
