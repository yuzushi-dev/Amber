"""
Active Vector Collection Resolver
================================

Helpers for selecting the per-tenant active vector collection.
"""

DEFAULT_TENANT_ID = "default"
DEFAULT_COLLECTION_PREFIX = "amber_"
DEFAULT_COLLECTION_NAME = "amber_default"


class ActiveCollectionPermissionError(Exception):
    """Raised when a non-super admin attempts to update active collection."""


def ensure_active_collection_update_allowed(is_super_admin: bool, update_dict: dict) -> None:
    """Guard updates to active_vector_collection to super admins only."""
    if "active_vector_collection" in update_dict and not is_super_admin:
        raise ActiveCollectionPermissionError(
            "Super Admin privileges required to update active_vector_collection"
        )


def resolve_active_vector_collection(tenant_id: str, config: dict | None) -> str:
    """Return the active collection name for a tenant.

    Prefers explicit tenant config; otherwise falls back to defaults.
    """
    active = (config or {}).get("active_vector_collection")
    if active:
        return active
    if tenant_id == DEFAULT_TENANT_ID:
        return DEFAULT_COLLECTION_NAME
    return f"{DEFAULT_COLLECTION_PREFIX}{tenant_id}"


def ensure_active_vector_collection_config(tenant_id: str, config: dict | None) -> dict:
    """Ensure tenant config includes an active collection, returning a new dict."""
    new_config = dict(config or {})
    if not new_config.get("active_vector_collection"):
        new_config["active_vector_collection"] = resolve_active_vector_collection(tenant_id, new_config)
    return new_config


def backfill_active_vector_collections(tenants) -> int:
    """Ensure all tenants have active_vector_collection set; return count updated."""
    updated = 0
    for tenant in tenants:
        config = tenant.config or {}
        new_config = ensure_active_vector_collection_config(tenant.id, config)
        if new_config != config:
            tenant.config = new_config
            updated += 1
    return updated
