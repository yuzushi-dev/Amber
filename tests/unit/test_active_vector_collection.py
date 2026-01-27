import pytest

from src.core.tenants.application.active_vector_collection import (
    ActiveCollectionPermissionError,
    backfill_active_vector_collections,
    ensure_active_collection_update_allowed,
    ensure_active_vector_collection_config,
    resolve_active_vector_collection,
)


def test_resolve_active_vector_collection_defaults():
    assert resolve_active_vector_collection("default", {}) == "amber_default"
    assert resolve_active_vector_collection("tenant-1", {}) == "amber_tenant-1"


def test_resolve_active_vector_collection_prefers_config():
    assert (
        resolve_active_vector_collection(
            "tenant-1", {"active_vector_collection": "custom_collection"}
        )
        == "custom_collection"
    )


def test_ensure_active_vector_collection_config_sets_missing():
    config = ensure_active_vector_collection_config("tenant-1", {})
    assert config["active_vector_collection"] == "amber_tenant-1"


class StubTenant:
    def __init__(self, tenant_id, config=None):
        self.id = tenant_id
        self.config = config


def test_backfill_active_vector_collections_updates_missing_only():
    tenants = [
        StubTenant("default", {}),
        StubTenant("t-1", None),
        StubTenant("t-2", {"active_vector_collection": "amber_custom"}),
    ]

    updated = backfill_active_vector_collections(tenants)

    assert updated == 2
    assert tenants[0].config["active_vector_collection"] == "amber_default"
    assert tenants[1].config["active_vector_collection"] == "amber_t-1"
    assert tenants[2].config["active_vector_collection"] == "amber_custom"


def test_active_collection_update_requires_super_admin():
    with pytest.raises(ActiveCollectionPermissionError):
        ensure_active_collection_update_allowed(False, {"active_vector_collection": "amber_x"})

    ensure_active_collection_update_allowed(True, {"active_vector_collection": "amber_x"})
    ensure_active_collection_update_allowed(False, {"top_k": 5})
