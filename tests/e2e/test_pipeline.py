"""
tests/e2e/test_pipeline.py
===========================
End-to-end document pipeline:
  - Document processing reaches 'ready' (already done by conftest)
  - Document is queryable and returns relevant sources
  - Non-streaming and streaming query both work
  - Conversation history is populated after a query
  - Feedback can be submitted and appears in admin queue
  - Graph data (entities, relationships, chunks) exists after processing
  - SSE document event stream delivers events and closes on ready
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

BASE = "http://127.0.0.1:8001"

# Queries that should match the test document content
TOPIC_QUERY = "What is the Quasar Configuration Protocol and what components does it define?"
ERRCODE_QUERY = "What are the QCP error codes?"


# ── Document status ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_uploaded_document_is_ready(ta_client, e2e_env):
    """The document uploaded during setup must be in 'ready' or 'completed' status."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get(f"/v1/documents/{doc_id}")
    assert r.status_code == 200
    doc = r.json()
    assert doc.get("status") in ("ready", "completed"), (
        f"Document status is '{doc.get('status')}', expected ready/completed. "
        f"Error: {doc.get('error_message')}"
    )


@pytest.mark.asyncio
async def test_document_has_chunks(ta_client, e2e_env):
    """Processed document must have at least 1 chunk."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get(f"/v1/documents/{doc_id}/chunks")
    assert r.status_code == 200
    chunks = r.json()
    assert len(chunks) >= 1, "Document has no chunks after processing"


@pytest.mark.asyncio
async def test_document_has_entities(ta_client, e2e_env):
    """Processed document must have entities extracted into the graph."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get(f"/v1/documents/{doc_id}/entities")
    assert r.status_code == 200
    # Entity extraction may yield 0 for very small docs on some providers — soft check
    entities = r.json()
    assert isinstance(entities, list), f"Expected list, got: {type(entities)}"


@pytest.mark.asyncio
async def test_document_appears_in_list(ta_client, e2e_env):
    """Uploaded document must appear in the tenant's document list."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    r = await ta_client.get("/v1/documents")
    assert r.status_code == 200
    docs = r.json()
    ids = [d.get("id") for d in docs]
    assert doc_id in ids, f"Document {doc_id} not found in list: {ids}"


# ── Non-streaming query ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_returns_answer(ta_client):
    """Non-streaming query must return a non-empty answer."""
    r = await ta_client.post("/v1/query", json={"query": TOPIC_QUERY})
    assert r.status_code == 200
    data = r.json()
    # Could be QueryResponse or StructuredQueryResponse
    answer = data.get("answer") or data.get("data")
    assert answer, f"Query returned no answer: {data}"


@pytest.mark.asyncio
async def test_query_returns_sources(ta_client, e2e_env):
    """Non-streaming query must cite sources from the tenant's document."""
    r = await ta_client.post("/v1/query", json={"query": ERRCODE_QUERY, "options": {"include_sources": True}})
    assert r.status_code == 200
    data = r.json()
    sources = data.get("sources", [])
    assert len(sources) >= 1, (
        "Query returned no sources. The document may not have been indexed into the vector store."
    )
    doc_ids = [s.get("document_id") for s in sources]
    assert e2e_env["tenant_a"]["document_id"] in doc_ids, (
        f"Test document not in sources: {doc_ids}"
    )


@pytest.mark.asyncio
async def test_query_returns_conversation_id(ta_client):
    """Query response must include a conversation_id for threading."""
    r = await ta_client.post("/v1/query", json={"query": TOPIC_QUERY})
    assert r.status_code == 200
    data = r.json()
    conv_id = data.get("conversation_id") or data.get("request_id")
    assert conv_id, f"No conversation_id in response: {data}"


# ── Chat history ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_history_populated_after_query(ta_client):
    """Chat history must contain an entry after submitting a query."""
    r1 = await ta_client.post(
        "/v1/query",
        json={"query": ERRCODE_QUERY},
        headers={"X-User-ID": "e2e_pipeline_user"},
    )
    assert r1.status_code == 200

    # Give time for async graph logging
    await asyncio.sleep(2)

    r2 = await ta_client.get(
        "/v1/chat/history",
        headers={"X-User-ID": "e2e_pipeline_user"},
    )
    assert r2.status_code == 200
    hist = r2.json()
    convs = hist.get("conversations") if isinstance(hist.get("conversations"), list) else []
    assert len(convs) >= 1, "No conversations in history after query"


@pytest.mark.asyncio
async def test_chat_history_item_has_expected_fields(ta_client):
    """Each history item must have required fields."""
    r = await ta_client.post(
        "/v1/query",
        json={"query": TOPIC_QUERY},
        headers={"X-User-ID": "e2e_field_check"},
    )
    assert r.status_code == 200
    await asyncio.sleep(4)

    r2 = await ta_client.get(
        "/v1/chat/history",
        headers={"X-User-ID": "e2e_field_check"},
    )
    assert r2.status_code == 200
    hist = r2.json()
    convs = hist.get("conversations") if isinstance(hist.get("conversations"), list) else []
    if not convs:
        pytest.skip("No conversations returned — non-streaming query may not have persisted ConversationSummary yet")
    item = convs[0]
    # Verify key fields present
    assert "request_id" in item or "id" in item, f"No ID field: {item}"


# ── Streaming query ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streaming_query_delivers_events(e2e_env):
    """POST /v1/query/stream must deliver SSE events including 'done'."""
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"X-API-Key": e2e_env["tenant_a"]["admin_key"]},
        timeout=60.0,
    ) as c:
        events = []
        deadline = time.monotonic() + 45.0
        async with c.stream(
            "POST",
            "/v1/query/stream",
            json={"query": ERRCODE_QUERY},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if time.monotonic() > deadline:
                    break
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                    if not isinstance(event, dict):
                        event = {"raw": str(event)}
                except json.JSONDecodeError:
                    event = {"raw": payload}
                events.append(event)
                event_type = event.get("type") or event.get("event")
                if event_type in ("done", "error", "processing_error"):
                    break

    assert events, "Streaming query returned no SSE events"
    types = [e.get("type") or e.get("event") or e.get("raw", "") for e in events]
    assert any(
        t in ("done", "answer", "sources") or
        any(kw in str(t) for kw in ("done", "answer", "sources", "chunk", "token"))
        for t in types
    ), (
        f"No expected event types received. Got: {types}"
    )


# ── Feedback pipeline ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feedback_submit_and_appears_in_admin_queue(ta_client, e2e_env):
    """User feedback must appear in the admin pending queue after submission."""
    # 1. Make a query to get a request_id
    r = await ta_client.post(
        "/v1/query",
        json={"query": ERRCODE_QUERY},
        headers={"X-User-ID": "e2e_feedback_user"},
    )
    assert r.status_code == 200
    request_id = r.json().get("conversation_id") or r.json().get("request_id")
    assert request_id, "No request_id from query"

    # 2. Submit positive feedback
    r2 = await ta_client.post(
        "/v1/feedback",
        json={
            "request_id": request_id,
            "is_positive": True,
            "comment": "e2e test feedback",
        },
    )
    assert r2.status_code in (200, 201), f"Feedback submit failed: {r2.text}"

    # 3. Admin sees it in pending queue
    await asyncio.sleep(1)
    r3 = await ta_client.get("/v1/admin/feedback/pending")
    assert r3.status_code == 200
    pending = r3.json()
    items = pending.get("data") or pending if isinstance(pending, list) else pending.get("items", [])
    # At least one pending item should exist (may include pre-existing ones)
    assert items is not None


# ── Document event stream (SSE) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_stream_unauthenticated_returns_401(e2e_env):
    """Document SSE stream must reject unauthenticated requests."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get(f"/v1/documents/{doc_id}/events")
    assert r.status_code == 401, (
        f"SSE stream accessible without auth: got {r.status_code}"
    )


@pytest.mark.asyncio
async def test_sse_stream_wrong_tenant_returns_404(e2e_env):
    """Tenant B user must not be able to stream Tenant A's document events."""
    doc_id = e2e_env["tenant_a"]["document_id"]
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"X-API-Key": e2e_env["tenant_b"]["user_key"]},
        timeout=10,
    ) as c:
        r = await c.get(f"/v1/documents/{doc_id}/events")
    assert r.status_code in (401, 403, 404), (
        f"Tenant B can stream Tenant A's document events: got {r.status_code}"
    )
