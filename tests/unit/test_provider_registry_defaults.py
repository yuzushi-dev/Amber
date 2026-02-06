from src.core.generation.infrastructure.providers.openai import (
    OpenAIEmbeddingProvider,
    OpenAILLMProvider,
)
from src.shared.model_registry import DEFAULT_EMBEDDING_MODEL, DEFAULT_LLM_MODEL


def test_openai_defaults_match_registry():
    assert OpenAILLMProvider.default_model == DEFAULT_LLM_MODEL["openai"]
    assert OpenAIEmbeddingProvider.default_model == DEFAULT_EMBEDDING_MODEL["openai"]
