"""
tests/e2e/test_isolation.py
============================
Tenant and user isolation guarantees:
  - Tenant A documents not visible to Tenant B users
  - Tenant A chat history not visible to Tenant B users
  - Tenant A query results don't include Tenant B documents
  - Super admin can read both tenants with X-Tenant-ID header
  - Tenant A cannot modify Tenant B's resources
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

BASE = "http://127.0.0.1:8001"

TOPIC_QUERY = "What is the Quasar Configuration Protocol?"


# ── Document isolation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_b_cannot_see_tenant_a_document(tb_user_client, e2e_env):
    """Tenant B user must not see Tenant A's document in their document list."""
    doc_id_a = e2e_env["tenant_a"]["document_id"]
    r = await tb_user_client.get("/v1/documents")
    assert r.status_code == 200
    docs = r.json()
    ids = [d.get("id") for d in docs]
    assert doc_id_a not in ids, (
        f"Tenant A document {doc_id_a} is visible in Tenant B document list — cross-tenant leak."
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_fetch_tenant_a_document_directly(tb_user_client, e2e_env):
    """Direct GET on Tenant A's document must return 404 for Tenant B."""
    doc_id_a = e2e_env["tenant_a"]["document_id"]
    r = await tb_user_client.get(f"/v1/documents/{doc_id_a}")
    assert r.status_code in (403, 404), (
        f"Tenant B fetched Tenant A document: got {r.status_code}. "
        "Cross-tenant document read is possible."
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_download_tenant_a_file(tb_user_client, e2e_env):
    """Tenant B must not be able to download Tenant A's original file."""
    doc_id_a = e2e_env["tenant_a"]["document_id"]
    r = await tb_user_client.get(f"/v1/documents/{doc_id_a}/file")
    assert r.status_code in (401, 403, 404), (
        f"Tenant B downloaded Tenant A file: {r.status_code}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_tenant_a_document(tb_user_client, e2e_env):
    """Tenant B must not be able to delete Tenant A's document."""
    doc_id_a = e2e_env["tenant_a"]["document_id"]
    r = await tb_user_client.delete(f"/v1/documents/{doc_id_a}")
    assert r.status_code in (401, 403, 404), (
        f"Tenant B deleted Tenant A document: {r.status_code}"
    )


@pytest.mark.asyncio
async def test_tenant_b_query_does_not_return_tenant_a_sources(tb_user_client, e2e_env):
    """Tenant B query results must not cite Tenant A documents as sources."""
    r = await tb_user_client.post("/v1/query", json={"query": TOPIC_QUERY})
    assert r.status_code == 200
    sources = r.json().get("sources", [])
    doc_id_a = e2e_env["tenant_a"]["document_id"]
    bad = [s for s in sources if s.get("document_id") == doc_id_a]
    assert not bad, (
        f"Tenant B query returned Tenant A document as source — cross-tenant RAG leak.\n"
        f"Sources: {sources}"
    )


# ── Chat history isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_b_cannot_see_tenant_a_chat_history(e2e_env):
    """Tenant B user must not see conversations from Tenant A."""
    # First, create a known conversation in Tenant A
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={
            "X-API-Key": e2e_env["tenant_a"]["user_key"],
            "X-User-ID": "e2e_isolation_user_a",
        },
        timeout=30,
    ) as c_a:
        r1 = await c_a.post("/v1/query", json={"query": TOPIC_QUERY})
        assert r1.status_code == 200
        conv_id = r1.json().get("conversation_id") or r1.json().get("request_id")

    await asyncio.sleep(2)

    # Tenant B should not see it in their history
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={
            "X-API-Key": e2e_env["tenant_b"]["user_key"],
            "X-User-ID": "e2e_isolation_user_b",
        },
        timeout=30,
    ) as c_b:
        r2 = await c_b.get("/v1/chat/history")
    assert r2.status_code == 200
    hist = r2.json()
    convs = hist.get("conversations") or (hist if isinstance(hist, list) else [])
    ids = [c.get("request_id") or c.get("id") for c in convs]
    assert conv_id not in ids, (
        f"Tenant A conversation {conv_id} visible in Tenant B history — cross-tenant history leak."
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_fetch_tenant_a_conversation_detail(e2e_env):
    """Direct GET on Tenant A conversation must return 404 for Tenant B."""
    # Create a conversation in Tenant A
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"X-API-Key": e2e_env["tenant_a"]["user_key"]},
        timeout=30,
    ) as c_a:
        r = await c_a.post("/v1/query", json={"query": TOPIC_QUERY})
        assert r.status_code == 200
        conv_id = r.json().get("conversation_id") or r.json().get("request_id")

    await asyncio.sleep(1)

    # Tenant B tries to read it
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"X-API-Key": e2e_env["tenant_b"]["user_key"]},
        timeout=30,
    ) as c_b:
        r2 = await c_b.get(f"/v1/chat/history/{conv_id}")
    assert r2.status_code in (403, 404), (
        f"Tenant B read Tenant A conversation detail: {r2.status_code}"
    )


# ── Admin keys are tenant-scoped ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_a_admin_key_list_scoped_to_own_tenant(ta_client, e2e_env):
    """Tenant A admin key listing must not include Tenant B's keys."""
    r = await ta_client.get("/v1/admin/keys")
    assert r.status_code == 200
    keys = r.json()
    key_ids = [k.get("id") for k in keys]
    # Tenant B admin key ID should not appear in Tenant A listing
    tb_admin_key_id = e2e_env["tenant_b"]["admin_key_id"]
    assert tb_admin_key_id not in key_ids, (
        "Tenant A sees Tenant B admin key in key list — cross-tenant key leak."
    )


# ── Super admin cross-tenant access ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_super_admin_can_see_tenant_a_docs_with_header(sa_client, e2e_env):
    """Super admin must be able to see Tenant A documents using X-Tenant-ID header."""
    doc_id_a = e2e_env["tenant_a"]["document_id"]
    r = await sa_client.get(
        f"/v1/documents/{doc_id_a}",
        headers={"X-Tenant-ID": e2e_env["tenant_a"]["id"]},
    )
    assert r.status_code == 200, (
        f"Super admin cannot access Tenant A document: {r.status_code} {r.text}"
    )


@pytest.mark.asyncio
async def test_super_admin_can_see_tenant_b_docs_with_header(sa_client, e2e_env):
    """Super admin must be able to see Tenant B documents using X-Tenant-ID header."""
    doc_id_b = e2e_env["tenant_b"]["document_id"]
    r = await sa_client.get(
        f"/v1/documents/{doc_id_b}",
        headers={"X-Tenant-ID": e2e_env["tenant_b"]["id"]},
    )
    assert r.status_code == 200, (
        f"Super admin cannot access Tenant B document: {r.status_code}"
    )
