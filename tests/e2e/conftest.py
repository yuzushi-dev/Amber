"""
E2E test suite for Amber2 — conftest.py
========================================
Fixtures that bootstrap 2 test tenants, 2 keys per tenant (admin + user),
and a small document per tenant, then tear everything down after the session.

Environment variables:
  AMBER_E2E_URL       Base URL of the running API  (default: http://127.0.0.1:8001)
  AMBER_ADMIN_KEY     Super-admin API key           (default: read from /root/amber2/.env)

All created resources are prefixed with "e2e_" + a 6-char run ID so parallel
runs don't collide and stale data is easy to identify.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio

# ── Environment ───────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("AMBER_E2E_URL", "http://127.0.0.1:8001")


def _read_admin_key() -> str:
    key = os.environ.get("AMBER_ADMIN_KEY")
    if key:
        return key
    env_path = "/root/amber2/.env"
    with open(env_path) as f:
        for line in f:
            if line.startswith("DEV_API_KEY="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError(f"AMBER_ADMIN_KEY not set and not found in {env_path}")


ADMIN_KEY = _read_admin_key()

# Short unique run-ID so test resources don't collide across parallel runs
RUN_ID = uuid.uuid4().hex[:6]

# ── Test document content (deterministic topic for verifiable RAG answers) ────

TEST_DOCUMENT_CONTENT = b"""# Amber2 E2E Test Document

## Quasar Configuration Protocol

The Quasar Configuration Protocol (QCP) is a fictional technical standard
used exclusively by Amber2 end-to-end integration tests. It defines how
widgets communicate with transceivers over a flux-capacitor interface.

### Key Components

1. **Flux Capacitor**: Enables bidirectional data transfer at 88 MHz.
2. **Widget Registry**: Stores widget metadata and firmware versions.
3. **Transceiver Matrix**: Handles multiplexed signal routing between nodes.

### Error Codes

- QCP-001: Widget not registered in registry
- QCP-002: Transceiver matrix overflow
- QCP-003: Flux capacitor synchronisation failure

### Maintenance

Widgets must be re-registered every 90 days via the Widget Registry API.
Transceiver firmware updates are applied automatically when the matrix
detects a version mismatch.
"""

TEST_DOCUMENT_FILENAME = "qcp_spec.txt"

# ── Low-level HTTP helpers ────────────────────────────────────────────────────


def _client(api_key: str, tenant_id: str | None = None) -> httpx.AsyncClient:
    headers = {"X-API-Key": api_key}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=90.0, follow_redirects=True)


async def _poll_document_ready(
    client: httpx.AsyncClient,
    document_id: str,
    timeout: float = 120.0,
    interval: float = 3.0,
) -> dict[str, Any]:
    """Poll GET /v1/documents/{id} until status=ready or failed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = await client.get(f"/v1/documents/{document_id}")
        assert r.status_code == 200, f"Document poll failed: {r.status_code} {r.text[:200]}"
        doc = r.json()
        status = doc.get("status", "")
        if status in ("ready", "completed"):
            return doc
        if status == "failed":
            raise AssertionError(f"Document processing failed: {doc.get('error_message')}")
        await asyncio.sleep(interval)
    raise TimeoutError(f"Document {document_id} not ready within {timeout}s")


# ── Session-scoped bootstrap ──────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_env():
    """
    Creates the full test environment and tears it down after the session.

    Yields a dict with keys:
      run_id, base_url, admin_key,
      tenant_a, tenant_b  (each: {id, name, admin_key, user_key, document_id})
    """
    async with _client(ADMIN_KEY) as sa:

        # ── Create 2 tenants ───────────────────────────────────────────────
        tenants = {}
        for tag in ("a", "b"):
            name = f"e2e_tenant_{tag}_{RUN_ID}"
            r = await sa.post("/v1/admin/tenants", json={"name": name})
            assert r.status_code in (200, 201), f"Tenant create failed: {r.text}"
            tenant = r.json()
            tenant_id = tenant.get("id") or tenant.get("data", {}).get("id")
            assert tenant_id, f"No tenant id in response: {tenant}"
            tenants[tag] = {"id": tenant_id, "name": name}

        # ── Create 2 keys per tenant (admin + user) ───────────────────────
        for tag, t in tenants.items():
            for role in ("admin", "user"):
                scopes = ["admin", "active_user"] if role == "admin" else ["active_user"]
                r = await sa.post(
                    "/v1/admin/keys",
                    json={
                        "name": f"e2e_{tag}_{role}_{RUN_ID}",
                        "scopes": scopes,
                        "prefix": "e2e",
                    },
                )
                assert r.status_code in (200, 201), f"Key create failed: {r.text}"
                body = r.json()
                raw_key = body.get("key")
                key_id = body.get("id")
                assert raw_key, f"No raw key in response: {body}"

                # Link key → tenant with role
                r2 = await sa.post(
                    f"/v1/admin/keys/{key_id}/tenants",
                    json={"tenant_id": t["id"], "role": role},
                )
                assert r2.status_code in (200, 201), f"Key link failed: {r2.text}"

                t[f"{role}_key"] = raw_key
                t[f"{role}_key_id"] = key_id

        # ── Upload 1 document per tenant, wait for ready ──────────────────
        for tag, t in tenants.items():
            async with _client(t["admin_key"]) as ac:
                r = await ac.post(
                    "/v1/documents",
                    files={"file": (TEST_DOCUMENT_FILENAME, TEST_DOCUMENT_CONTENT, "text/plain")},
                )
                assert r.status_code in (200, 201, 202), f"Upload failed [{tag}]: {r.text}"
                body = r.json()
                doc_id = (
                    body.get("document_id")
                    or body.get("id")
                    or (body.get("data") or {}).get("document_id")
                    or (body.get("data") or {}).get("id")
                )
                assert doc_id, f"No document_id in upload response: {body}"
                t["document_id"] = doc_id

                # Wait for full processing
                await _poll_document_ready(ac, doc_id, timeout=600.0)

        env = {
            "run_id": RUN_ID,
            "base_url": BASE_URL,
            "admin_key": ADMIN_KEY,
            "tenant_a": tenants["a"],
            "tenant_b": tenants["b"],
        }

        yield env

        # ── Teardown: delete both tenants (cascades keys + docs) ──────────
        for tag, t in tenants.items():
            try:
                r = await sa.delete(f"/v1/admin/tenants/{t['id']}")
                # 204 = deleted, 404 = already gone
                assert r.status_code in (200, 204, 404), f"Tenant delete failed [{tag}]: {r.text}"
            except Exception as exc:
                print(f"WARNING: teardown error for tenant {tag}: {exc}")


# ── Convenience per-test clients ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def sa_client(e2e_env):
    """Super-admin httpx client."""
    async with _client(e2e_env["admin_key"]) as c:
        yield c


@pytest_asyncio.fixture
async def ta_client(e2e_env):
    """Tenant-A admin httpx client."""
    async with _client(e2e_env["tenant_a"]["admin_key"]) as c:
        yield c


@pytest_asyncio.fixture
async def tu_client(e2e_env):
    """Tenant-A regular-user httpx client."""
    async with _client(e2e_env["tenant_a"]["user_key"]) as c:
        yield c


@pytest_asyncio.fixture
async def tb_admin_client(e2e_env):
    """Tenant-B admin httpx client."""
    async with _client(e2e_env["tenant_b"]["admin_key"]) as c:
        yield c


@pytest_asyncio.fixture
async def tb_user_client(e2e_env):
    """Tenant-B regular-user httpx client."""
    async with _client(e2e_env["tenant_b"]["user_key"]) as c:
        yield c
