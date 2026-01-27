import pytest
from types import SimpleNamespace
from fastapi import HTTPException

from src.api.routes.admin import config as config_module


@pytest.mark.asyncio
async def test_update_tenant_config_blocks_active_collection_for_non_super_admin(monkeypatch):
    class FakeRequest:
        state = SimpleNamespace(is_super_admin=False)

    class FakeSession:
        async def execute(self, query):
            class Result:
                def scalar_one_or_none(self):
                    return SimpleNamespace(id="t-1", config={})
            return Result()

        def add(self, obj):
            return None

        async def commit(self):
            return None

    class FakeSessionMaker:
        def __call__(self):
            class CM:
                async def __aenter__(self):
                    return FakeSession()
                async def __aexit__(self, exc_type, exc, tb):
                    return False
            return CM()

    monkeypatch.setattr(config_module, "async_session_maker", FakeSessionMaker())

    update = config_module.TenantConfigUpdate(active_vector_collection="amber_x")

    with pytest.raises(HTTPException) as exc:
        await config_module.update_tenant_config("t-1", update, FakeRequest())

    assert exc.value.status_code == 403
