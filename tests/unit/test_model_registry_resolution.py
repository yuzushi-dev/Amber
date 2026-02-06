import pytest

from src.core.generation.domain.provider_models import ConfigurationError
from src.shared import model_registry as mr
from src.shared.model_registry import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
    EMBEDDING_MODELS,
    LLM_MODELS,
)


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OPENAI_DEFAULT = DEFAULT_LLM_MODEL["openai"]
OPENAI_ALT = _first_other(LLM_MODELS["openai"], OPENAI_DEFAULT)
ANTHROPIC_MODEL = next(iter(LLM_MODELS["anthropic"]))
OLLAMA_MODEL = DEFAULT_LLM_MODEL["ollama"]


def test_resolve_provider_for_model_unique():
    providers = {ANTHROPIC_MODEL: {"anthropic"}}
    assert mr.resolve_provider_for_model(ANTHROPIC_MODEL, providers, kind="llm") == "anthropic"


def test_resolve_provider_for_model_ambiguous():
    providers = {OPENAI_DEFAULT: {"openai", "ollama"}}
    with pytest.raises(ConfigurationError) as exc:
        mr.resolve_provider_for_model(OPENAI_DEFAULT, providers, kind="llm")
    assert OPENAI_DEFAULT in str(exc.value)
    assert "openai" in str(exc.value)
    assert "ollama" in str(exc.value)


def test_parse_fallback_chain():
    default = [(OPENAI_DEFAULT, OPENAI_DEFAULT)]
    assert mr.parse_fallback_chain(
        f"openai:{OPENAI_ALT},anthropic:{DEFAULT_LLM_MODEL['anthropic']},ollama:{OLLAMA_MODEL}",
        default=default,
    ) == [
        ("openai", OPENAI_ALT),
        ("anthropic", DEFAULT_LLM_MODEL["anthropic"]),
        ("ollama", OLLAMA_MODEL),
    ]


def test_resolve_token_encoding_llm_models():
    model = next(iter(mr.TOKEN_ENCODING_BY_MODEL))
    assert mr.resolve_token_encoding(model) == mr.TOKEN_ENCODING_BY_MODEL[model]
    assert mr.resolve_token_encoding(OPENAI_DEFAULT) == mr.TOKEN_ENCODING_BY_PROVIDER["openai"]
    assert (
        mr.resolve_token_encoding(DEFAULT_LLM_MODEL["anthropic"])
        == mr.TOKEN_ENCODING_BY_PROVIDER["anthropic"]
    )


def test_resolve_token_encoding_embedding_models():
    assert (
        mr.resolve_token_encoding(DEFAULT_EMBEDDING_MODEL["openai"])
        == mr.TOKEN_ENCODING_BY_PROVIDER["openai"]
    )
    assert (
        mr.resolve_token_encoding(DEFAULT_EMBEDDING_MODEL["ollama"])
        == mr.TOKEN_ENCODING_BY_PROVIDER["ollama"]
    )


def test_openai_chat_overrides_reasoning_models():
    model = next(iter(mr.OPENAI_CHAT_MODEL_OVERRIDES))
    overrides = mr.get_openai_chat_overrides(model)
    assert overrides["use_max_completion_tokens"] is True
    assert overrides["fixed_temperature"] == 1.0


def test_openai_chat_overrides_default_models():
    non_override = _first_other(LLM_MODELS["openai"], next(iter(mr.OPENAI_CHAT_MODEL_OVERRIDES)))
    overrides = mr.get_openai_chat_overrides(non_override)
    assert overrides["use_max_completion_tokens"] is False
    assert overrides["fixed_temperature"] is None


def test_embedding_supports_dimensions_openai():
    supports = [
        name for name, info in EMBEDDING_MODELS["openai"].items() if info.get("supports_dimensions")
    ]
    legacy = [
        name
        for name, info in EMBEDDING_MODELS["openai"].items()
        if not info.get("supports_dimensions")
    ]
    assert mr.embedding_supports_dimensions(supports[0], provider="openai") is True
    assert mr.embedding_supports_dimensions(supports[1], provider="openai") is True
    assert mr.embedding_supports_dimensions(legacy[0], provider="openai") is False
