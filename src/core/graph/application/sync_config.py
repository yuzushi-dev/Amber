from dataclasses import dataclass
from typing import Any


DEFAULT_GRAPH_SYNC_PROFILE = "default"
DEFAULT_GRAPH_SYNC_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "initial_concurrency": 3,
        "max_concurrency": 5,
        "adaptive_concurrency_enabled": False,
        "use_gleaning": True,
        "max_gleaning_steps": 1,
        "cache_enabled": False,
        "cache_ttl_hours": 168,
        "smart_gleaning_enabled": False,
        "smart_gleaning_entity_threshold": 2,
        "smart_gleaning_relationship_threshold": 1,
        "smart_gleaning_min_chunk_chars": 250,
    },
    "local_weak": {
        "initial_concurrency": 1,
        "max_concurrency": 2,
        "adaptive_concurrency_enabled": False,
        "use_gleaning": True,
        "max_gleaning_steps": 1,
        "cache_enabled": False,
        "cache_ttl_hours": 168,
        "smart_gleaning_enabled": False,
        "smart_gleaning_entity_threshold": 2,
        "smart_gleaning_relationship_threshold": 1,
        "smart_gleaning_min_chunk_chars": 250,
    },
    "cloud_strong": {
        "initial_concurrency": 3,
        "max_concurrency": 5,
        "adaptive_concurrency_enabled": False,
        "use_gleaning": True,
        "max_gleaning_steps": 1,
        "cache_enabled": False,
        "cache_ttl_hours": 168,
        "smart_gleaning_enabled": False,
        "smart_gleaning_entity_threshold": 2,
        "smart_gleaning_relationship_threshold": 1,
        "smart_gleaning_min_chunk_chars": 250,
    },
}


@dataclass(frozen=True)
class GraphSyncRuntimeConfig:
    profile: str
    initial_concurrency: int
    max_concurrency: int
    adaptive_concurrency_enabled: bool
    use_gleaning: bool
    max_gleaning_steps: int
    cache_enabled: bool
    cache_ttl_hours: int
    smart_gleaning_enabled: bool
    smart_gleaning_entity_threshold: int
    smart_gleaning_relationship_threshold: int
    smart_gleaning_min_chunk_chars: int


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        data = value.model_dump()
        if isinstance(data, dict):
            return data

    if hasattr(value, "dict"):
        data = value.dict()
        if isinstance(data, dict):
            return data

    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_") and not callable(item)
        }

    return {}


def _merge_profiles(base: dict[str, dict[str, Any]], incoming: Any) -> dict[str, dict[str, Any]]:
    incoming_profiles = _to_dict(incoming)
    if not incoming_profiles:
        return base

    merged = {name: values.copy() for name, values in base.items()}
    for profile_name, profile_values in incoming_profiles.items():
        profile_dict = _to_dict(profile_values)
        current = merged.get(profile_name, {}).copy()
        current.update(profile_dict)
        merged[profile_name] = current
    return merged


def resolve_graph_sync_runtime_config(
    settings: Any | None,
    tenant_config: dict[str, Any] | None = None,
) -> GraphSyncRuntimeConfig:
    """
    Resolve static graph sync runtime settings.

    Priority:
    1. Built-in defaults
    2. Application settings.graph_sync
    3. tenant_config["graph_sync"]
    """
    profiles = {name: values.copy() for name, values in DEFAULT_GRAPH_SYNC_PROFILES.items()}
    profile_name = DEFAULT_GRAPH_SYNC_PROFILE

    settings_graph_sync = _to_dict(getattr(settings, "graph_sync", None))
    if settings_graph_sync:
        profiles = _merge_profiles(profiles, settings_graph_sync.get("profiles"))
        profile_name = settings_graph_sync.get("profile", profile_name)

    tenant_graph_sync = _to_dict((tenant_config or {}).get("graph_sync"))
    if tenant_graph_sync:
        profiles = _merge_profiles(profiles, tenant_graph_sync.get("profiles"))
        profile_name = tenant_graph_sync.get("profile", profile_name)

        # Support direct per-tenant overrides without profile map.
        direct_overrides = {
            key: tenant_graph_sync[key]
            for key in ("initial_concurrency", "use_gleaning", "max_gleaning_steps")
            if key in tenant_graph_sync
        }
        if direct_overrides:
            selected = profiles.get(profile_name, profiles[DEFAULT_GRAPH_SYNC_PROFILE]).copy()
            selected.update(direct_overrides)
            profiles[profile_name] = selected

    selected_profile = profiles.get(profile_name, profiles[DEFAULT_GRAPH_SYNC_PROFILE])

    initial_concurrency = max(1, int(selected_profile.get("initial_concurrency", 3)))
    max_concurrency = max(initial_concurrency, int(selected_profile.get("max_concurrency", 5)))
    adaptive_concurrency_enabled = bool(selected_profile.get("adaptive_concurrency_enabled", False))
    max_gleaning_steps = max(0, int(selected_profile.get("max_gleaning_steps", 1)))
    use_gleaning = bool(selected_profile.get("use_gleaning", True))
    cache_enabled = bool(selected_profile.get("cache_enabled", False))
    cache_ttl_hours = max(1, int(selected_profile.get("cache_ttl_hours", 168)))
    smart_gleaning_enabled = bool(selected_profile.get("smart_gleaning_enabled", False))
    smart_gleaning_entity_threshold = max(
        0, int(selected_profile.get("smart_gleaning_entity_threshold", 2))
    )
    smart_gleaning_relationship_threshold = max(
        0, int(selected_profile.get("smart_gleaning_relationship_threshold", 1))
    )
    smart_gleaning_min_chunk_chars = max(
        0, int(selected_profile.get("smart_gleaning_min_chunk_chars", 250))
    )

    return GraphSyncRuntimeConfig(
        profile=profile_name,
        initial_concurrency=initial_concurrency,
        max_concurrency=max_concurrency,
        adaptive_concurrency_enabled=adaptive_concurrency_enabled,
        use_gleaning=use_gleaning,
        max_gleaning_steps=max_gleaning_steps,
        cache_enabled=cache_enabled,
        cache_ttl_hours=cache_ttl_hours,
        smart_gleaning_enabled=smart_gleaning_enabled,
        smart_gleaning_entity_threshold=smart_gleaning_entity_threshold,
        smart_gleaning_relationship_threshold=smart_gleaning_relationship_threshold,
        smart_gleaning_min_chunk_chars=smart_gleaning_min_chunk_chars,
    )
