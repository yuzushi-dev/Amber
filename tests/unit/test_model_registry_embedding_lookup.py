from src.shared.model_registry import (
    embedding_native_dimensions,
    embedding_supports_dimensions,
)


def test_native_dimensions_exact_name():
    assert embedding_native_dimensions("nomic-embed-text", provider="ollama") == 768


def test_native_dimensions_with_tag_falls_back_to_base_name():
    assert embedding_native_dimensions("nomic-embed-text:latest", provider="ollama") == 768


def test_unknown_model_returns_none():
    assert embedding_native_dimensions("no-such-model", provider="ollama") is None


def test_supports_dimensions_matryoshka_model():
    assert embedding_supports_dimensions("text-embedding-3-small", provider="openai") is True


def test_supports_dimensions_with_tag():
    assert embedding_supports_dimensions("nomic-embed-text:latest", provider="ollama") is False
