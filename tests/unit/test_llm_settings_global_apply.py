from types import SimpleNamespace

import pytest

from src.api.routes.admin import config as config_module


class Result:
    def __init__(self, tenants):
        self._tenants = tenants

    def scalars(self):
        return SimpleNamespace(all=lambda: self._tenants)

    def scalar_one_or_none(self):
        return self._tenants[0] if self._tenants else None


class StubTenant:
    def __init__(self, tenant_id, config=None):
        self.id = tenant_id
        self.config = config


class FakeSession:
    def __init__(self, tenants):
        self._tenants = tenants
        self.committed = False

    async def execute(self, query):
        return Result(self._tenants)

    def add(self, obj):
        return None

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_super_admin_llm_update_applies_to_all_tenants(monkeypatch):
    tenants = [
        StubTenant("default", {"llm_provider": "old", "top_k": 5}),
        StubTenant("t-1", {"llm_provider": "old", "top_k": 3}),
    ]
    fake_session = FakeSession(tenants)

    class FakeSessionMaker:
        def __call__(self):
            class CM:
                async def __aenter__(self):
                    return fake_session

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return CM()

    class FakeTuningService:
        def __init__(self, session_maker):
            return None

        async def log_change(self, **kwargs):
            return None

    async def fake_get_tenant_config(tenant_id: str):
        return {"tenant_id": tenant_id}

    monkeypatch.setattr(config_module, "async_session_maker", FakeSessionMaker())
    monkeypatch.setattr(config_module, "TuningService", FakeTuningService)
    monkeypatch.setattr(config_module, "get_tenant_config", fake_get_tenant_config)

    class FakeRequest:
        state = SimpleNamespace(is_super_admin=True)

    update = config_module.TenantConfigUpdate(llm_provider="new", top_k=9)

    await config_module.update_tenant_config("default", update, FakeRequest())

    assert tenants[0].config["llm_provider"] == "new"
    assert tenants[1].config["llm_provider"] == "new"
    assert tenants[0].config["top_k"] == 9
    assert tenants[1].config["top_k"] == 3


@pytest.mark.asyncio
async def test_llm_model_write_through_generation_model(monkeypatch):
    tenants = [StubTenant("default", {"llm_model": "old"})]
    fake_session = FakeSession(tenants)

    class FakeSessionMaker:
        def __call__(self):
            class CM:
                async def __aenter__(self):
                    return fake_session

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return CM()

    class FakeTuningService:
        def __init__(self, session_maker):
            return None

        async def log_change(self, **kwargs):
            return None

    async def fake_get_tenant_config(tenant_id: str):
        return {"tenant_id": tenant_id}

    monkeypatch.setattr(config_module, "async_session_maker", FakeSessionMaker())
    monkeypatch.setattr(config_module, "TuningService", FakeTuningService)
    monkeypatch.setattr(config_module, "get_tenant_config", fake_get_tenant_config)

    class FakeRequest:
        state = SimpleNamespace(is_super_admin=True)

    update = config_module.TenantConfigUpdate(llm_model="new-model")

    await config_module.update_tenant_config("default", update, FakeRequest())

    assert tenants[0].config["llm_model"] == "new-model"
    assert tenants[0].config["generation_model"] == "new-model"
