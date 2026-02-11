from types import SimpleNamespace

from src.core.graph.application.sync_config import resolve_graph_sync_runtime_config


def test_graph_sync_config_defaults_without_settings():
    cfg = resolve_graph_sync_runtime_config(settings=None, tenant_config=None)

    assert cfg.profile == "default"
    assert cfg.initial_concurrency == 3
    assert cfg.max_concurrency == 5
    assert cfg.adaptive_concurrency_enabled is False
    assert cfg.use_gleaning is True
    assert cfg.max_gleaning_steps == 1
    assert cfg.cache_enabled is False
    assert cfg.smart_gleaning_enabled is False


def test_graph_sync_config_uses_settings_profile():
    settings = SimpleNamespace(
        graph_sync=SimpleNamespace(
            profile="local_weak",
            profiles={
                "default": {"initial_concurrency": 3, "use_gleaning": True, "max_gleaning_steps": 1},
                "local_weak": {
                    "initial_concurrency": 1,
                    "max_concurrency": 2,
                    "adaptive_concurrency_enabled": True,
                    "use_gleaning": False,
                    "max_gleaning_steps": 0,
                },
            },
        )
    )

    cfg = resolve_graph_sync_runtime_config(settings=settings, tenant_config=None)
    assert cfg.profile == "local_weak"
    assert cfg.initial_concurrency == 1
    assert cfg.max_concurrency == 2
    assert cfg.adaptive_concurrency_enabled is True
    assert cfg.use_gleaning is False
    assert cfg.max_gleaning_steps == 0


def test_graph_sync_config_tenant_overrides_settings():
    settings = SimpleNamespace(
        graph_sync=SimpleNamespace(
            profile="default",
            profiles={
                "default": {"initial_concurrency": 3, "use_gleaning": True, "max_gleaning_steps": 1},
            },
        )
    )
    tenant_config = {
        "graph_sync": {
            "profile": "tenant_profile",
            "profiles": {
                "tenant_profile": {
                    "initial_concurrency": 2,
                    "max_concurrency": 4,
                    "adaptive_concurrency_enabled": True,
                    "use_gleaning": True,
                    "max_gleaning_steps": 2,
                }
            },
        }
    }

    cfg = resolve_graph_sync_runtime_config(settings=settings, tenant_config=tenant_config)
    assert cfg.profile == "tenant_profile"
    assert cfg.initial_concurrency == 2
    assert cfg.max_concurrency == 4
    assert cfg.adaptive_concurrency_enabled is True
    assert cfg.use_gleaning is True
    assert cfg.max_gleaning_steps == 2


def test_graph_sync_config_supports_cache_and_smart_gleaning_flags():
    settings = SimpleNamespace(
        graph_sync=SimpleNamespace(
            profile="default",
            profiles={
                "default": {
                    "initial_concurrency": 3,
                    "use_gleaning": True,
                    "max_gleaning_steps": 1,
                    "cache_enabled": True,
                    "cache_ttl_hours": 24,
                    "smart_gleaning_enabled": True,
                    "smart_gleaning_entity_threshold": 3,
                    "smart_gleaning_relationship_threshold": 2,
                    "smart_gleaning_min_chunk_chars": 100,
                },
            },
        )
    )

    cfg = resolve_graph_sync_runtime_config(settings=settings, tenant_config=None)
    assert cfg.cache_enabled is True
    assert cfg.cache_ttl_hours == 24
    assert cfg.smart_gleaning_enabled is True
    assert cfg.smart_gleaning_entity_threshold == 3
    assert cfg.smart_gleaning_relationship_threshold == 2
    assert cfg.smart_gleaning_min_chunk_chars == 100
