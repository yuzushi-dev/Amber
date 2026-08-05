import pytest
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_llm_steps_schema():
    from src.api.routes.admin.config import get_llm_steps

    result = await get_llm_steps()

    assert "steps" in result
    assert any(step["id"] == "ingestion.graph_extraction" for step in result["steps"])


@pytest.mark.asyncio
async def test_llm_settings_update_requires_super_admin(monkeypatch):
    from src.api.routes.admin.config import TenantConfigUpdate, update_tenant_config

    class DummyState:
        is_super_admin = False

    class DummyRequest:
        state = DummyState()

    def fail_session_maker():
        raise AssertionError("Session should not be created when super admin guard triggers")

    monkeypatch.setattr("src.api.routes.admin.config.async_session_maker", fail_session_maker)

    update = TenantConfigUpdate(llm_provider="openai")

    with pytest.raises(HTTPException) as exc:
        await update_tenant_config("default", update, DummyRequest())

    assert exc.value.status_code == 403


def test_llm_step_override_valid_pair_passes():
    from src.api.routes.admin.config import LLMStepOverride
    from src.shared.model_registry import DEFAULT_LLM_MODEL

    override = LLMStepOverride(provider="openai", model=DEFAULT_LLM_MODEL["openai"])

    assert override.provider == "openai"
    assert override.model == DEFAULT_LLM_MODEL["openai"]


def test_llm_step_override_both_none_passes():
    from src.api.routes.admin.config import LLMStepOverride

    override = LLMStepOverride()

    assert override.provider is None
    assert override.model is None


def test_llm_step_override_unknown_model_rejected_with_alternatives():
    from src.api.routes.admin.config import LLMStepOverrideInput
    from src.shared.model_registry import LLM_MODELS

    with pytest.raises(ValidationError) as exc:
        LLMStepOverrideInput(provider="openai", model="gpt-retired-999")

    message = str(exc.value)
    assert "gpt-retired-999" in message
    for known_model in LLM_MODELS["openai"]:
        assert known_model in message


def test_llm_step_override_response_model_accepts_legacy_out_of_registry_value():
    """Regression test for issue #98 (B1). `TenantConfigResponse.llm_steps`
    (the READ path) must stay permissive: a tenant that already has an
    out-of-registry value stored (e.g. saved via `amber llm set-step
    --force`, or a model the curated registry hasn't caught up with yet)
    must remain READABLE. Wiring the validated `LLMStepOverrideInput` (or
    re-adding the validator to the shared base class) into this field would
    turn GET (and PUT, which re-reads to respond)
    /api/admin/config/tenants/{id} into a 500 for that tenant, with no way
    to see or fix the bad value."""
    from src.api.routes.admin.config import TenantConfigResponse

    # Must not raise.
    response = TenantConfigResponse(
        tenant_id="default",
        config={},
        llm_steps={"chat.generation": {"provider": "openai", "model": "gpt-retired-999"}},
    )

    assert response.llm_steps["chat.generation"].model == "gpt-retired-999"


def test_llm_step_override_input_model_only_resolved_against_any_provider():
    """`LLMStepOverrideInput` (the write-path/request variant) must accept a
    model-only override when the model is known to ANY registered provider
    (issue #98, B2) -- the effective provider for that case is resolved
    elsewhere (tenant_config/settings), not visible to this isolated field."""
    from src.api.routes.admin.config import LLMStepOverrideInput

    override = LLMStepOverrideInput(model="gpt-4o-mini")  # no provider given

    assert override.model == "gpt-4o-mini"

    with pytest.raises(ValidationError):
        LLMStepOverrideInput(model="definitely-not-a-real-model")
