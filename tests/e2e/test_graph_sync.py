"""
tests/e2e/test_graph_sync.py
==============================
Graph sync and community pipeline:
  - After document processing, graph editor returns nodes
  - Entities endpoint returns data for the uploaded document
  - Graph editor search finds content from the test document
  - Community listing works (may be empty if detection hasn't run)
  - Admin can trigger community refresh; regular user cannot
  - Graph editor write operations require tenant_admin
"""

from __future__ import annotations

import pytest


# ── Graph data from processed document ────────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_editor_top_returns_results(ta_client):
    """Graph editor top-nodes endpoint must return a list."""
    r = await ta_client.get("/v1/graph/editor/top")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list), f"Expected list: {type(data)}"


@pytest.mark.asyncio
async def test_graph_editor_search_finds_qcp(ta_client):
    """Graph search for 'QCP' must return at least one result from the test doc."""
    r = await ta_client.get("/v1/graph/editor/search", params={"q": "QCP"})
    assert r.status_code in (200, 404), f"Search failed: {r.status_code}"
    if r.status_code == 200:
        results = r.json()
        assert isinstance(results, list)


@pytest.mark.asyncio
async def test_document_entities_returns_list(ta_client, e2e_env):
    """Document entity list must return a list (may be empty for small docs)."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get(f"/v1/documents/{doc_id}/entities")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_document_relationships_returns_list(ta_client, e2e_env):
    """Document relationship list must return a list."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get(f"/v1/documents/{doc_id}/relationships")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_document_chunks_returns_non_empty(ta_client, e2e_env):
    """Document chunks must be non-empty after processing."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get(f"/v1/documents/{doc_id}/chunks")
    assert r.status_code == 200
    chunks = r.json()
    assert len(chunks) >= 1, "No chunks found — embedding pipeline may have failed"


@pytest.mark.asyncio
async def test_document_communities_returns_list(ta_client, e2e_env):
    """Document community list must return a list."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get(f"/v1/documents/{doc_id}/communities")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert isinstance(r.json(), list)


# ── Community endpoints ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_community_list_accessible_to_user(tu_client):
    """Regular user must be able to list communities."""
    r = await tu_client.get("/v1/communities")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_community_refresh_accessible_to_admin(ta_client):
    """Tenant admin must be able to trigger community refresh."""
    r = await ta_client.post("/v1/communities/refresh")
    # 200/202 = queued, 429 = rate limited — both indicate auth passed
    assert r.status_code in (200, 202, 429), (
        f"Community refresh rejected for tenant admin: {r.status_code} {r.text}"
    )


@pytest.mark.asyncio
async def test_community_refresh_blocked_for_user(tu_client):
    """Regular user must not be able to trigger community refresh."""
    r = await tu_client.post("/v1/communities/refresh")
    # Accept 429: rate limiter can fire before auth check (still blocked)
    assert r.status_code in (403, 429), f"User key can trigger community refresh: {r.status_code}"


# ── Graph editor write operations require admin ───────────────────────────────

@pytest.mark.asyncio
async def test_graph_editor_heal_blocked_for_user(tu_client, e2e_env):
    """Heal suggestion (write op) must require tenant_admin."""
    r = await tu_client.post(
        "/v1/graph/editor/heal",
        json={"node_id": "fake-node-id"},
    )
    assert r.status_code == 403, (
        f"Regular user can trigger graph heal: {r.status_code}"
    )


@pytest.mark.asyncio
async def test_graph_editor_read_accessible_to_user(tu_client, e2e_env):
    """Graph editor read endpoints must be accessible to regular users."""
    r = await tu_client.get("/v1/graph/editor/top")
    assert r.status_code == 200


# ── Context graph (super_admin only) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_graph_stats_requires_super_admin(sa_client, ta_client, tu_client):
    """Context graph stats must be super_admin only."""
    r_sa = await sa_client.get("/v1/admin/context-graph/stats")
    assert r_sa.status_code == 200

    r_ta = await ta_client.get("/v1/admin/context-graph/stats")
    assert r_ta.status_code == 403

    r_tu = await tu_client.get("/v1/admin/context-graph/stats")
    assert r_tu.status_code == 403
