from src.core.generation.application.llm_steps import (
    inspect_llm_step_registry,
    resolve_llm_step_config,
    validate_llm_step_override,
)
from src.shared.model_registry import DEFAULT_LLM_MODEL, LLM_MODELS


def _first_other(models: dict, current: str) -> str:
    for name in models:
        if name != current:
            return name
    return current


OPENAI_DEFAULT = DEFAULT_LLM_MODEL["openai"]
OPENAI_ALT = _first_other(LLM_MODELS["openai"], OPENAI_DEFAULT)
ANTHROPIC_DEFAULT = DEFAULT_LLM_MODEL["anthropic"]


class DummySettings:
    default_llm_provider = "openai"
    default_llm_model = OPENAI_DEFAULT
    default_llm_temperature = 0.0
    seed = 42


def test_resolve_llm_step_config_fallbacks():
    tenant_config = {
        "llm_provider": "anthropic",
        "llm_model": ANTHROPIC_DEFAULT,
        "llm_steps": {"ingestion.graph_extraction": {"temperature": 0.2, "seed": 123}},
    }

    cfg = resolve_llm_step_config(
        tenant_config=tenant_config,
        step_id="ingestion.graph_extraction",
        settings=DummySettings(),
    )

    assert cfg.temperature == 0.2
    assert cfg.seed == 123
    assert cfg.provider == "anthropic"
    assert cfg.model == ANTHROPIC_DEFAULT


def test_resolve_llm_step_config_generation_model_fallback():
    tenant_config = {"generation_model": OPENAI_ALT}

    cfg = resolve_llm_step_config(
        tenant_config=tenant_config,
        step_id="ingestion.graph_extraction",
        settings=DummySettings(),
    )

    assert cfg.model == OPENAI_ALT


def test_validate_llm_step_override_valid_pair_passes():
    assert validate_llm_step_override("openai", OPENAI_DEFAULT) is None


def test_validate_llm_step_override_both_none_passes():
    assert validate_llm_step_override(None, None) is None


def test_validate_llm_step_override_unknown_model_lists_alternatives():
    error = validate_llm_step_override("openai", "gpt-retired-999")
    assert error is not None
    assert "gpt-retired-999" in error
    assert "openai" in error
    for known_model in LLM_MODELS["openai"]:
        assert known_model in error


def test_validate_llm_step_override_unknown_provider_lists_known_providers():
    error = validate_llm_step_override("not-a-real-provider", "some-model")
    assert error is not None
    assert "not-a-real-provider" in error
    for known_provider in LLM_MODELS:
        assert known_provider in error


def test_validate_llm_step_override_model_only_resolved_against_any_provider():
    """Regression test for issue #98 (B2). A model-only override (no
    provider given) must be checked against ALL known providers -- the
    prior behavior ("provider is None => nothing to check") let an invalid
    model slip through whenever it was merged with a provider from
    elsewhere (tenant_config/settings, or an already-stored override)."""
    assert validate_llm_step_override(None, OPENAI_DEFAULT) is None

    error = validate_llm_step_override(None, "definitely-not-a-real-model")
    assert error is not None
    assert "definitely-not-a-real-model" in error


def test_validate_llm_step_override_provider_only_passes():
    """A provider-only override (no model given) has nothing to check --
    the model comes from elsewhere."""
    assert validate_llm_step_override("openai", None) is None


# --- inspect_llm_step_registry (issue #107: periodic registry-drift sweep) ---
#
# Companion to validate_llm_step_override: that one is used at write-time (PUT
# tenant config) and raises/rejects. This one is read-only and used by the
# periodic Celery beat sweep (check_llm_registry_drift) to catch drift
# introduced *after* a write -- e.g. a provider retiring a model that was
# valid when the tenant's `llm_steps` override was last saved.


def test_inspect_llm_step_registry_no_overrides_returns_no_findings():
    assert inspect_llm_step_registry("tenant-1", {}) == []


def test_inspect_llm_step_registry_legacy_model_reports_info_finding():
    findings = inspect_llm_step_registry("tenant-1", {"llm_model": "gemma3:12b"})

    assert len(findings) == 1
    assert findings[0]["tenant_id"] == "tenant-1"
    assert findings[0]["step_id"] == "*"
    assert findings[0]["severity"] == "info"
    assert findings[0]["code"] == "legacy_fallback"
    assert "gemma3:12b" in findings[0]["message"]


def test_inspect_llm_step_registry_valid_override_reports_nothing():
    tenant_config = {
        "llm_steps": {
            "ingestion.chunk_context": {"provider": "openai", "model": OPENAI_DEFAULT}
        }
    }

    assert inspect_llm_step_registry("tenant-1", tenant_config) == []


def test_inspect_llm_step_registry_flags_retired_model_as_error():
    """Reproduces the issue #107 reference bug: a tenant with a step pinned
    to a model that is no longer known to the registry (e.g. retired from
    Ollama) must be flagged, not silently ignored."""
    tenant_config = {
        "llm_steps": {
            "ingestion.chunk_context": {"provider": "ollama", "model": "gemma3:12b"}
        }
    }

    findings = inspect_llm_step_registry("tenant-1", tenant_config)

    assert len(findings) == 1
    finding = findings[0]
    assert finding["tenant_id"] == "tenant-1"
    assert finding["step_id"] == "ingestion.chunk_context"
    assert finding["severity"] == "error"
    assert finding["code"] in {"unknown_provider", "unavailable_model"}
    assert "gemma3:12b" in finding["message"]


def test_inspect_llm_step_registry_flags_unknown_step_id():
    tenant_config = {"llm_steps": {"not.a.real.step": {"provider": "openai"}}}

    findings = inspect_llm_step_registry("tenant-1", tenant_config)

    assert len(findings) == 1
    assert findings[0]["code"] == "unknown_step"
    assert findings[0]["severity"] == "error"


def test_inspect_llm_step_registry_flags_non_dict_override():
    tenant_config = {"llm_steps": {"ingestion.chunk_context": "not-a-dict"}}

    findings = inspect_llm_step_registry("tenant-1", tenant_config)

    assert len(findings) == 1
    assert findings[0]["code"] == "invalid_override"


def test_inspect_llm_step_registry_flags_non_dict_llm_steps():
    findings = inspect_llm_step_registry("tenant-1", {"llm_steps": "not-a-dict"})

    assert len(findings) == 1
    assert findings[0]["code"] == "invalid_llm_steps"
    assert findings[0]["step_id"] == "*"
