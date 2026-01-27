from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.admin_ops.application.api_key_service import ApiKeyService
from src.core.tenants.domain.tenant import Tenant


class Result:
    def __init__(self, scalar=None, scalars_first=None):
        self._scalar = scalar
        self._scalars_first = scalars_first

    def scalars(self):
        return SimpleNamespace(first=lambda: self._scalars_first)

    def scalar_one_or_none(self):
        return self._scalar


@pytest.mark.asyncio
async def test_bootstrap_sets_active_collection_on_default_tenant():
    session = SimpleNamespace()
    session.execute = AsyncMock(
        side_effect=[
            Result(scalars_first=None),  # ApiKey lookup
            Result(scalar=None),         # Tenant lookup
            Result(scalar=None),         # ApiKeyTenant lookup
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()

    service = ApiKeyService(session)
    service.create_key_from_raw = AsyncMock(return_value=SimpleNamespace(id="key-1"))

    await service.ensure_bootstrap_key("raw-key", name="Bootstrap Key")

    added = [call.args[0] for call in session.add.call_args_list]
    tenant = next(obj for obj in added if isinstance(obj, Tenant))

    assert tenant.config["active_vector_collection"] == "amber_default"
