import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_llm_steps_schema():
    from src.api.routes.admin.config import get_llm_steps

    result = await get_llm_steps()

    assert "steps" in result
    assert any(step["id"] == "ingestion.graph_extraction" for step in result["steps"])


@pytest.mark.asyncio
async def test_llm_settings_update_requires_super_admin(monkeypatch):
    from src.api.routes.admin.config import update_tenant_config, TenantConfigUpdate

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
