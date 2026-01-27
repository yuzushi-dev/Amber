import pytest
from types import SimpleNamespace

from src.api.routes.admin import config as config_module


class Result:
    def __init__(self, tenants):
        self._tenants = tenants

    def scalars(self):
        return SimpleNamespace(all=lambda: self._tenants)


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

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_backfill_route_updates_missing(monkeypatch):
    tenants = [
        StubTenant("default", {}),
        StubTenant("t-1", None),
        StubTenant("t-2", {"active_vector_collection": "amber_custom"}),
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

    monkeypatch.setattr(config_module, "async_session_maker", FakeSessionMaker())

    response = await config_module.backfill_active_vector_collection()

    assert response["updated"] == 2
    assert tenants[0].config["active_vector_collection"] == "amber_default"
    assert tenants[1].config["active_vector_collection"] == "amber_t-1"
    assert tenants[2].config["active_vector_collection"] == "amber_custom"
    assert fake_session.committed is True
