"""
Security tests: admin route guards (Tasks 2 & 3).

Every admin sub-router that handles privileged operations must declare
either verify_super_admin or verify_tenant_admin as a router-level
dependency so no individual handler is reachable without the guard.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


def _non_admin_req(tenant_id="t1"):
    req = MagicMock()
    req.state.is_super_admin = False
    req.state.tenant_role = None
    req.state.permissions = ["active_user"]
    req.state.tenant_id = tenant_id
    return req


def _tenant_admin_req(tenant_id="t1"):
    req = MagicMock()
    req.state.is_super_admin = False
    req.state.tenant_role = "tenant_admin"
    req.state.permissions = ["active_user", "tenant_admin"]
    req.state.tenant_id = tenant_id
    return req


# ── helper: check router-level dependency ─────────────────────────────────────

def _router_has_dep(router, *dep_names):
    """Return True if router has any of dep_names as a router-level Depends."""
    for dep in router.dependencies:
        fn = dep.dependency
        name = getattr(fn, "__name__", repr(fn))
        if any(d in name for d in dep_names):
            return True
    return False


# ── super_admin routes ────────────────────────────────────────────────────────

@pytest.mark.parametrize("module_name,router_attr", [
    ("src.api.routes.admin.backup",      "router"),
    ("src.api.routes.admin.jobs",        "router"),
    ("src.api.routes.admin.observability","router"),
    ("src.api.routes.admin.providers",   "router"),
    ("src.api.routes.admin.embeddings",  "router"),
    ("src.api.routes.admin.maintenance", "router"),
    ("src.api.routes.admin.context_graph","router"),
])
def test_super_admin_router_has_guard(module_name, router_attr):
    """Router must declare verify_super_admin as a router-level dependency."""
    import importlib
    mod = importlib.import_module(module_name)
    router = getattr(mod, router_attr)
    assert _router_has_dep(router, "super_admin"), (
        f"{module_name}.{router_attr} is missing verify_super_admin dependency. "
        "Any authenticated key can reach this route."
    )


@pytest.mark.asyncio
async def test_super_admin_rejects_non_admin():
    """verify_super_admin raises 403 for non-super-admin requests."""
    from src.api.deps import verify_super_admin
    req = _non_admin_req()
    with pytest.raises(HTTPException) as exc_info:
        await verify_super_admin(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_rejects_tenant_admin():
    """verify_super_admin raises 403 for tenant_admin (not super_admin) requests."""
    from src.api.deps import verify_super_admin
    req = _tenant_admin_req()
    with pytest.raises(HTTPException) as exc_info:
        await verify_super_admin(req)
    assert exc_info.value.status_code == 403


# ── tenant_admin routes ───────────────────────────────────────────────────────

@pytest.mark.parametrize("module_name,router_attr", [
    ("src.api.routes.admin.curation",  "router"),
    ("src.api.routes.admin.retention", "router"),
    ("src.api.routes.admin.feedback",  "router"),
])
def test_tenant_admin_router_has_guard(module_name, router_attr):
    """Router must declare verify_tenant_admin (or higher) as a dependency."""
    import importlib
    mod = importlib.import_module(module_name)
    router = getattr(mod, router_attr)
    assert _router_has_dep(router, "tenant_admin", "super_admin"), (
        f"{module_name}.{router_attr} is missing verify_tenant_admin dependency. "
        "Any authenticated tenant member can reach moderation/retention/feedback actions."
    )


@pytest.mark.asyncio
async def test_tenant_admin_rejects_plain_user():
    """verify_tenant_admin raises 403 for plain tenant user requests."""
    from src.api.deps import verify_tenant_admin
    req = _non_admin_req()
    with pytest.raises(HTTPException) as exc_info:
        await verify_tenant_admin(req)
    assert exc_info.value.status_code == 403


# ── tenants.py mutating ops upgraded to super_admin ───────────────────────────

def test_tenants_create_delete_patch_require_super_admin():
    """
    tenant create/delete/patch must require verify_super_admin, not just verify_admin.
    """
    import src.api.routes.admin.tenants as t_module
    from src.api.deps import verify_super_admin

    # Check POST (create), DELETE, PATCH all declare verify_super_admin
    for route in t_module.router.routes:
        method_set = {m.upper() for m in getattr(route, "methods", [])}
        if method_set & {"POST", "DELETE", "PATCH"}:
            dep_fns = [d.dependency for d in getattr(route, "dependencies", [])]
            assert verify_super_admin in dep_fns, (
                f"tenants.py {method_set} route missing verify_super_admin. "
                f"Found deps: {[getattr(f,'__name__',repr(f)) for f in dep_fns]}"
            )
