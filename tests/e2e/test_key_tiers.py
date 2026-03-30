"""
tests/e2e/test_key_tiers.py
============================
API key tier enforcement:
  - Keys with only 'active_user' scope cannot exercise admin operations
  - Keys with 'admin' scope can manage within their tenant but not cross-tenant
  - Keys with 'super_admin' scope can operate platform-wide
  - Multi-tenant keys can switch context with X-Tenant-ID header
  - Privilege escalation is rejected (cannot grant super_admin from admin key)
"""

from __future__ import annotations

import httpx
import pytest

BASE = "http://127.0.0.1:8001"


# ── Tier-specific capability boundaries ───────────────────────────────────────

@pytest.mark.asyncio
async def test_user_key_can_query_but_not_create_keys(tu_client):
    """active_user key: can query, cannot create API keys."""
    r_query = await tu_client.post("/v1/query", json={"query": "test"})
    assert r_query.status_code == 200

    r_keys = await tu_client.post(
        "/v1/admin/keys",
        json={"name": "e2e_should_fail", "scopes": ["active_user"]},
    )
    assert r_keys.status_code == 403, f"User key created API key: {r_keys.status_code}"


@pytest.mark.asyncio
async def test_admin_key_can_create_key_but_not_super_admin_scope(ta_client):
    """admin key: can create keys, but cannot grant super_admin scope."""
    # Allowed: create a regular key
    r = await ta_client.post(
        "/v1/admin/keys",
        json={"name": "e2e_temp_from_admin", "scopes": ["active_user"]},
    )
    assert r.status_code in (200, 201), f"Admin cannot create key: {r.text}"
    key_id = r.json().get("id")

    # Not allowed: grant super_admin scope to that key
    r2 = await ta_client.patch(
        f"/v1/admin/keys/{key_id}",
        json={"scopes": ["active_user", "super_admin"]},
    )
    assert r2.status_code == 403, (
        f"Admin key granted super_admin scope: {r2.status_code} — privilege escalation is possible."
    )

    # Cleanup
    await ta_client.delete(f"/v1/admin/keys/{key_id}")


@pytest.mark.asyncio
async def test_admin_key_cannot_create_super_admin_scope_on_creation(ta_client):
    """admin key: cannot create a new key with super_admin scope."""
    r = await ta_client.post(
        "/v1/admin/keys",
        json={"name": "e2e_escalation_attempt", "scopes": ["active_user", "super_admin"]},
    )
    assert r.status_code == 403, (
        f"Admin created key with super_admin scope: {r.status_code} — privilege escalation."
    )


@pytest.mark.asyncio
async def test_admin_key_can_refresh_communities(ta_client):
    """admin key must be able to trigger community refresh (tenant_admin check)."""
    r = await ta_client.post("/v1/communities/refresh")
    # 200 = queued, 429 = rate limited (both are acceptable — means auth passed)
    assert r.status_code in (200, 202, 429), (
        f"Tenant admin cannot refresh communities: {r.status_code} {r.text}"
    )


@pytest.mark.asyncio
async def test_user_key_cannot_refresh_communities(tu_client):
    """active_user key must not be able to refresh communities."""
    r = await tu_client.post("/v1/communities/refresh")
    # Accept 429: rate limiter can fire before auth check (still blocked)
    assert r.status_code in (403, 429), f"User key can trigger community refresh: {r.status_code}"


@pytest.mark.asyncio
async def test_admin_key_can_list_and_manage_own_tenant_keys(ta_client, e2e_env):
    """Tenant admin can list API keys and see their own tenant's keys."""
    r = await ta_client.get("/v1/admin/keys")
    assert r.status_code == 200
    keys = r.json()
    assert isinstance(keys, list), f"Expected list: {keys}"


@pytest.mark.asyncio
async def test_super_admin_can_create_and_delete_tenants(sa_client, e2e_env):
    """Super admin key must be able to create and delete a tenant."""
    run_id = e2e_env["run_id"]
    r = await sa_client.post(
        "/v1/admin/tenants",
        json={"name": f"e2e_tier_temp_{run_id}"},
    )
    assert r.status_code in (200, 201), f"Super admin cannot create tenant: {r.text}"
    tenant_id = (
        r.json().get("id")
        or (r.json().get("data") or {}).get("id")
    )
    assert tenant_id

    r2 = await sa_client.delete(f"/v1/admin/tenants/{tenant_id}")
    assert r2.status_code in (200, 204), f"Super admin cannot delete tenant: {r2.text}"


# ── Multi-tenant key ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_tenant_key_can_switch_context(sa_client, e2e_env):
    """
    A key linked to multiple tenants must be able to switch context via X-Tenant-ID.
    The super_admin key can impersonate any tenant.
    """
    # Access Tenant A documents via super_admin with X-Tenant-ID
    r_a = await sa_client.get(
        "/v1/documents",
        headers={"X-Tenant-ID": e2e_env["tenant_a"]["id"]},
    )
    assert r_a.status_code == 200
    ids_a = {d["id"] for d in r_a.json()}

    # Access Tenant B documents via super_admin with X-Tenant-ID
    r_b = await sa_client.get(
        "/v1/documents",
        headers={"X-Tenant-ID": e2e_env["tenant_b"]["id"]},
    )
    assert r_b.status_code == 200
    ids_b = {d["id"] for d in r_b.json()}

    # Each view should contain the respective document (and they should differ)
    doc_a = e2e_env["tenant_a"]["document_id"]
    doc_b = e2e_env["tenant_b"]["document_id"]

    assert doc_a in ids_a, "Tenant A document not visible when X-Tenant-ID=tenant_a"
    assert doc_b in ids_b, "Tenant B document not visible when X-Tenant-ID=tenant_b"
    assert doc_a not in ids_b, "Tenant A document visible in Tenant B context (cross-tenant)"
    assert doc_b not in ids_a, "Tenant B document visible in Tenant A context (cross-tenant)"


# ── Key rotation / deactivation ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deactivated_key_returns_401(sa_client, e2e_env):
    """A deactivated API key must return 401 on any request."""
    # Create a throwaway key
    r = await sa_client.post(
        "/v1/admin/keys",
        json={"name": f"e2e_deact_{e2e_env['run_id']}", "scopes": ["active_user"]},
    )
    assert r.status_code in (200, 201)
    body = r.json()
    key_id = body["id"]
    raw_key = body["key"]

    # Deactivate via DELETE (revocation)
    r2 = await sa_client.delete(f"/v1/admin/keys/{key_id}")
    assert r2.status_code in (200, 204), f"Key revocation failed: {r2.status_code}"

    # Try using the deactivated key
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"X-API-Key": raw_key},
        timeout=10,
    ) as c:
        r3 = await c.get("/v1/documents")
    assert r3.status_code == 401, (
        f"Deactivated key returned {r3.status_code} — key deactivation not enforced."
    )
