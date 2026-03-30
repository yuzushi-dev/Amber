"""
Security tests for conversation history gaps.

Covers:
- admin/chat_history.py requires super_admin
- query.py agent mode writes resolved user_id (not "user")
- query.py threading update checks tenant ownership
- query.py RAG update checks tenant+user ownership
"""

import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch as mpatch


# ── Helper factories ─────────────────────────────────────────────────────────


def _make_request(tenant_id="tenant-a", api_key_name="key-001", user_id_header=None):
    req = MagicMock()
    req.method = "POST"
    req.state.tenant_id = tenant_id
    req.state.api_key_name = api_key_name
    req.state.is_super_admin = False
    req.state.tenant_role = None
    headers = {}
    if user_id_header:
        headers["X-User-ID"] = user_id_header
    req.headers = headers
    return req


def _non_admin_request():
    req = _make_request()
    req.state.is_super_admin = False
    req.state.permissions = ["active_user"]
    return req


# ── Fix 1: admin/chat_history.py — router-level guard ───────────────────────


@pytest.mark.asyncio
async def test_chat_history_admin_rejects_non_admin():
    """
    admin/chat_history.py must reject non-super-admin callers with 403.
    Any key that is not super_admin must be blocked.
    """
    from fastapi import HTTPException
    from src.api.deps import verify_super_admin

    req = _non_admin_request()
    with pytest.raises(HTTPException) as exc_info:
        await verify_super_admin(req)
    assert exc_info.value.status_code == 403


def test_chat_history_router_has_super_admin_dependency():
    """
    admin/chat_history.py router must declare verify_super_admin as a dependency
    so no individual handler can be reached without super_admin.
    """
    import src.api.routes.admin.chat_history as ch_module
    from src.api.deps import verify_super_admin

    router = ch_module.router
    dep_fns = [d.dependency for d in router.dependencies]
    assert verify_super_admin in dep_fns, (
        "admin/chat_history router is missing verify_super_admin dependency. "
        "Any authenticated key can list or delete conversations across all tenants."
    )


# ── Fix 2: agent mode writes resolved user_id ────────────────────────────────


def test_query_py_no_hardcoded_user_sentinel_in_agent_insert():
    """
    query.py must not contain the literal user_id=\"user\" string used for
    agent-mode conversation inserts.  The resolved principal must be used instead.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert 'user_id="user",  # Default user' not in source, (
        "query.py still contains user_id='user' for agent conversation inserts. "
        "All agent conversations will be stored under a shared 'user' identity."
    )


def test_query_py_agent_insert_uses_stream_user_id():
    """
    query.py agent-mode ConversationSummary insert must reference stream_user_id,
    the caller-resolved principal set earlier in generate_stream().
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert "user_id=stream_user_id" in source, (
        "query.py agent insert does not reference stream_user_id. "
        "Agent conversations will be attributed to wrong identity."
    )


# ── Fix 3: stream_user_id is resolved before sticky/agent blocks ─────────────


def test_query_py_stream_user_id_resolved_early():
    """
    generate_stream() must resolve stream_user_id before the sticky mode check
    so it is available for both the sticky check and the agent/RAG persist blocks.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    stream_pos = source.find("stream_user_id = _get_user_id(")
    sticky_pos = source.find("# STICKY MODE CHECK")
    assert stream_pos != -1, "stream_user_id not resolved in generate_stream"
    assert stream_pos < sticky_pos, (
        "stream_user_id must be resolved BEFORE the sticky mode check block."
    )


# ── Fix 4: tenant ownership checked before threading update ──────────────────


def test_query_py_sticky_check_verifies_tenant():
    """
    The sticky mode check must compare existing_conv.tenant_id against the
    caller's tenant_id before trusting conversation mode metadata.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert "existing_conv.tenant_id != tenant_id" in source, (
        "Sticky mode check does not verify tenant ownership. "
        "A caller can auto-switch into agent mode using a foreign tenant's conversation ID."
    )


def test_query_py_rag_update_verifies_tenant_and_user():
    """
    The RAG-mode ConversationSummary update block must check both
    tenant_id and user_id before appending to an existing conversation.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    assert (
        "existing_summary.tenant_id != tenant_id or existing_summary.user_id != stream_user_id"
        in source
    ), (
        "RAG update does not check tenant+user ownership. "
        "A caller who knows a conversation_id can append to another user's history."
    )


def test_query_py_agent_update_verifies_tenant():
    """
    The agent-mode ConversationSummary update block must check tenant_id
    before appending to an existing conversation.
    """
    import src.api.routes.query as q_module

    source = inspect.getsource(q_module)
    # Look for the ownership check added in the agent update block
    assert "Conversation not found" in source and "existing_summary.tenant_id != tenant_id" in source, (
        "Agent update block does not verify tenant ownership. "
        "A caller can append to a foreign-tenant conversation thread."
    )
