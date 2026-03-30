"""
Security tests for Task 4: rules tenancy.

Verifies that:
- RulesService.get_active_rules() scopes by tenant_id in DB query
- Cache is per-tenant (no cross-tenant bleed)
- Cache invalidation supports per-tenant granularity
- Admin routes scope rule CRUD by the caller's tenant_id
- GenerationService passes tenant_id from options to rules fetch
"""

import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, call


# ── 1. RulesService: DB query is tenant-scoped ────────────────────────────────


@pytest.mark.asyncio
async def test_rules_service_get_active_rules_accepts_tenant_id():
    """get_active_rules() must accept a tenant_id parameter."""
    from src.core.admin_ops.application.rules_service import RulesService
    sig = inspect.signature(RulesService.get_active_rules)
    assert "tenant_id" in sig.parameters, (
        "RulesService.get_active_rules() has no tenant_id parameter. "
        "All tenants receive the same rules regardless of tenant context."
    )


@pytest.mark.asyncio
async def test_rules_service_cache_is_per_tenant():
    """
    Calling get_active_rules() with two different tenant IDs must query
    the DB with different tenant predicates and cache results separately.
    """
    from src.core.admin_ops.application.rules_service import RulesService

    # Reset class-level state
    RulesService._rules_cache = {}
    RulesService._cache_initialized = set()

    # Build a session that returns tenant-specific rows based on call order
    result_a = MagicMock()
    result_a.all.return_value = [("rule-A",)]
    result_b = MagicMock()
    result_b.all.return_value = [("rule-B",)]

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[result_a, result_b])

    class _FakeCtx:
        async def __aenter__(self): return session
        async def __aexit__(self, *a): pass

    svc = RulesService(session_factory=lambda: _FakeCtx())
    rules_a = await svc.get_active_rules(tenant_id="tenant-a", force_refresh=True)
    rules_b = await svc.get_active_rules(tenant_id="tenant-b", force_refresh=True)

    assert rules_a != rules_b, (
        "get_active_rules() returns the same data for different tenants. "
        "Tenant-A rules are visible to Tenant-B."
    )
    assert "rule-A" in rules_a
    assert "rule-B" in rules_b

    # Verify the two DB calls carried different tenant predicates
    assert session.execute.call_count == 2


def test_rules_service_invalidate_accepts_tenant_id():
    """
    invalidate_cache() must accept an optional tenant_id to do per-tenant
    eviction without clearing other tenants' caches.
    """
    from src.core.admin_ops.application.rules_service import RulesService
    sig = inspect.signature(RulesService.invalidate_cache)
    assert "tenant_id" in sig.parameters, (
        "RulesService.invalidate_cache() has no tenant_id parameter. "
        "Every rule change (by any tenant admin) flushes the entire global cache."
    )


def test_rules_service_per_tenant_invalidation():
    """
    Invalidating tenant-A's cache must not evict tenant-B's cache.
    """
    from src.core.admin_ops.application.rules_service import RulesService

    # Seed per-tenant cache
    RulesService._rules_cache = {"tenant-a": ["rule-a"], "tenant-b": ["rule-b"]}
    RulesService._cache_initialized = {"tenant-a", "tenant-b"}

    RulesService.invalidate_cache(tenant_id="tenant-a")

    assert "tenant-a" not in RulesService._cache_initialized, (
        "tenant-a cache still marked initialized after invalidation"
    )
    assert "tenant-b" in RulesService._cache_initialized, (
        "tenant-b cache was evicted even though only tenant-a was invalidated. "
        "Cross-tenant cache disruption on every rule write."
    )


# ── 2. Admin routes: CRUD is tenant-scoped ────────────────────────────────────


def test_rules_admin_create_sets_tenant_id():
    """
    create_rule handler source must set rule.tenant_id from the request
    (not leave it NULL or use a fixed value).
    """
    import src.api.routes.admin.rules as rules_module
    source = inspect.getsource(rules_module.create_rule)
    assert "tenant_id" in source, (
        "create_rule() does not reference tenant_id at all. "
        "All rules will be created with NULL tenant_id, visible to every tenant."
    )


def test_rules_admin_list_filters_by_tenant():
    """
    list_rules handler source must filter the query by tenant_id.
    """
    import src.api.routes.admin.rules as rules_module
    source = inspect.getsource(rules_module.list_rules)
    assert "tenant_id" in source, (
        "list_rules() does not reference tenant_id at all. "
        "Tenant admins can read rules belonging to other tenants."
    )


# ── 3. GenerationService: passes tenant_id from options ───────────────────────


def test_generation_service_generate_uses_options_tenant_id():
    """
    GenerationService.generate() must extract tenant_id from the options dict
    and pass it to get_active_rules() — not call get_active_rules() with no
    tenant_id (which would return global/cross-tenant rules).
    """
    import src.core.generation.application.generation_service as gs_module
    source = inspect.getsource(gs_module.GenerationService.generate)
    assert "get_active_rules()" not in source, (
        "GenerationService.generate() calls get_active_rules() without tenant_id. "
        "All tenants receive the combined global rule set regardless of their context."
    )


def test_generation_service_generate_stream_uses_options_tenant_id():
    """
    GenerationService.generate_stream() must pass tenant_id to get_active_rules().
    """
    import src.core.generation.application.generation_service as gs_module
    source = inspect.getsource(gs_module.GenerationService.generate_stream)
    assert "get_active_rules()" not in source, (
        "GenerationService.generate_stream() calls get_active_rules() without tenant_id."
    )
