from src.core.tenants.application.llm_model_backfill import backfill_llm_model_config
from src.shared.model_registry import DEFAULT_LLM_MODEL, LLM_MODELS


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OPENAI_DEFAULT = DEFAULT_LLM_MODEL["openai"]
OPENAI_ALT = _first_other(LLM_MODELS["openai"], OPENAI_DEFAULT)


def test_backfill_adds_llm_model_from_generation_model():
    original = {"generation_model": OPENAI_ALT, "top_k": 10}
    updated, changed = backfill_llm_model_config(original)

    assert changed is True
    assert updated["llm_model"] == OPENAI_ALT
    assert updated["generation_model"] == OPENAI_ALT
    assert updated["top_k"] == 10
    assert "llm_model" not in original


def test_backfill_adds_generation_model_from_llm_model():
    original = {"llm_model": OPENAI_DEFAULT}
    updated, changed = backfill_llm_model_config(original)

    assert changed is True
    assert updated["llm_model"] == OPENAI_DEFAULT
    assert updated["generation_model"] == OPENAI_DEFAULT


def test_backfill_no_changes_when_both_present():
    original = {"llm_model": OPENAI_DEFAULT, "generation_model": OPENAI_ALT}
    updated, changed = backfill_llm_model_config(original)

    assert changed is False
    assert updated == original


def test_backfill_no_changes_when_missing_both():
    original = {"top_k": 5}
    updated, changed = backfill_llm_model_config(original)

    assert changed is False
    assert updated == original
