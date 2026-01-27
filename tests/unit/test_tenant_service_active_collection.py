import pytest

from src.core.tenants.application import tenant_service as tenant_service_module


class StubTenant:
    def __init__(self, name, api_key_prefix=None, config=None, id=None):
        self.id = id
        self.name = name
        self.api_key_prefix = api_key_prefix
        self.config = config or {}


class FakeSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if isinstance(obj, StubTenant) and not getattr(obj, "id", None):
                obj.id = "tenant-1"

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


@pytest.mark.asyncio
async def test_create_tenant_sets_active_collection():
    tenant_service_module.Tenant = StubTenant
    session = FakeSession()
    service = tenant_service_module.TenantService(session)

    tenant = await service.create_tenant("Test Tenant", None, {})

    assert tenant.config["active_vector_collection"] == "amber_tenant-1"
