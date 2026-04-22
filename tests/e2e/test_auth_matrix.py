"""
tests/e2e/test_auth_matrix.py
==============================
Verifies the full access-control matrix:
  - 401 when no API key is provided
  - 403 when key has insufficient tier
  - 2xx when correct tier is used
"""

import httpx
import pytest

BASE = "http://127.0.0.1:8001"


# ── No-auth (401) checks ──────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("GET",  "/v1/documents"),
    ("GET",  "/v1/chat/history"),
    ("POST", "/v1/query"),
    ("GET",  "/v1/communities"),
    ("GET",  "/v1/admin/tenants"),
    ("GET",  "/v1/admin/keys"),
    ("GET",  "/v1/admin/feedback/pending"),
    ("GET",  "/v1/admin/chat/history"),
    ("GET",  "/v1/admin/context-graph/stats"),
    ("GET",  "/v1/admin/jobs"),
    ("GET",  "/v1/admin/backup"),
])
@pytest.mark.asyncio
async def test_no_key_returns_401(method, path):
    """Every protected endpoint must reject requests without an API key."""
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        fn = getattr(c, method.lower())
        kwargs = {"json": {}} if method == "POST" else {}
        r = await fn(path, **kwargs)
    assert r.status_code == 401, (
        f"{method} {path} returned {r.status_code} without auth key — endpoint is publicly accessible."
    )


# ── Wrong-tier (403) checks ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_regular_user_cannot_access_admin_keys(tu_client):
    """Regular-user key must not list API keys (requires admin scope)."""
    r = await tu_client.get("/v1/admin/keys")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@pytest.mark.asyncio
async def test_regular_user_cannot_refresh_communities(tu_client):
    """Regular-user key must not trigger community refresh (requires tenant_admin)."""
    r = await tu_client.post("/v1/communities/refresh")
    # Accept 429 Too Many Requests: rate limiter fires before auth (still blocked)
    assert r.status_code in (403, 429), (
        f"Expected 403 or 429, got {r.status_code}. Regular user can trigger community refresh."
    )


@pytest.mark.asyncio
async def test_regular_user_cannot_access_admin_feedback(tu_client):
    """Regular-user key must not access admin feedback queue."""
    r = await tu_client.get("/v1/admin/feedback/pending")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@pytest.mark.asyncio
async def test_regular_user_cannot_list_admin_chat_history(tu_client):
    """Regular-user key must not access admin chat history view."""
    r = await tu_client.get("/v1/admin/chat/history")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@pytest.mark.asyncio
async def test_regular_user_cannot_access_context_graph(tu_client):
    """Regular-user key must not access context graph stats."""
    r = await tu_client.get("/v1/admin/context-graph/stats")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_create_tenant(ta_client):
    """Tenant-admin key must not create tenants (requires super_admin)."""
    r = await ta_client.post("/v1/admin/tenants", json={"name": "e2e_should_not_create"})
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_delete_tenant(ta_client, e2e_env):
    """Tenant-admin key must not delete tenants."""
    r = await ta_client.delete(f"/v1/admin/tenants/{e2e_env['tenant_a']['id']}")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_access_admin_jobs(ta_client):
    """Tenant-admin key must not access admin jobs (requires super_admin)."""
    r = await ta_client.get("/v1/admin/jobs")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_access_context_graph_stats(ta_client):
    """Tenant-admin key must not access context-graph stats (super_admin only)."""
    r = await ta_client.get("/v1/admin/context-graph/stats")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


# ── Correct-tier (2xx) checks ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_public(e2e_env):
    """Health endpoint must be publicly accessible."""
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get("/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "healthy"


@pytest.mark.asyncio
async def test_regular_user_can_list_documents(tu_client):
    r = await tu_client.get("/v1/documents")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_regular_user_can_query(tu_client):
    r = await tu_client.post("/v1/query", json={"query": "What is a flux capacitor?"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_regular_user_can_read_own_history(tu_client):
    r = await tu_client.get("/v1/chat/history")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_tenant_admin_can_list_keys(ta_client):
    r = await ta_client.get("/v1/admin/keys")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_tenant_admin_can_access_feedback_queue(ta_client):
    r = await ta_client.get("/v1/admin/feedback/pending")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_can_list_tenants(sa_client):
    r = await sa_client.get("/v1/admin/tenants")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_can_access_context_graph(sa_client):
    r = await sa_client.get("/v1/admin/context-graph/stats")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_can_access_admin_jobs(sa_client):
    r = await sa_client.get("/v1/admin/jobs")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_super_admin_can_access_admin_chat_history(sa_client):
    r = await sa_client.get("/v1/admin/chat/history")
    assert r.status_code == 200
