from src.core.tenants.application.llm_model_backfill import backfill_llm_model_config


def test_backfill_adds_llm_model_from_generation_model():
    original = {"generation_model": "gpt-4o-mini", "top_k": 10}
    updated, changed = backfill_llm_model_config(original)

    assert changed is True
    assert updated["llm_model"] == "gpt-4o-mini"
    assert updated["generation_model"] == "gpt-4o-mini"
    assert updated["top_k"] == 10
    assert "llm_model" not in original


def test_backfill_adds_generation_model_from_llm_model():
    original = {"llm_model": "gpt-4.1-mini"}
    updated, changed = backfill_llm_model_config(original)

    assert changed is True
    assert updated["llm_model"] == "gpt-4.1-mini"
    assert updated["generation_model"] == "gpt-4.1-mini"


def test_backfill_no_changes_when_both_present():
    original = {"llm_model": "gpt-4.1-mini", "generation_model": "gpt-4o-mini"}
    updated, changed = backfill_llm_model_config(original)

    assert changed is False
    assert updated == original


def test_backfill_no_changes_when_missing_both():
    original = {"top_k": 5}
    updated, changed = backfill_llm_model_config(original)

    assert changed is False
    assert updated == original
