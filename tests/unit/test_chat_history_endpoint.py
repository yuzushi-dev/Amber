"""
Tests for ZTD-1822: User-facing GET /chat/history endpoint must return
conversations scoped to the authenticated user and tenant.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_conversation(id: str, tenant_id: str, user_id: str, title: str):
    conv = MagicMock()
    conv.id = id
    conv.tenant_id = tenant_id
    conv.user_id = user_id
    conv.title = title
    conv.summary = f"Summary of {title}"
    conv.created_at = datetime(2026, 1, 1)
    conv.metadata_ = {"query": title, "answer": f"Answer to {title}"}
    return conv


@pytest.mark.asyncio
async def test_history_scoped_to_user_and_tenant():
    """list_history must filter by both tenant_id and user_id."""
    from src.api.routes.chat import list_history

    conversations = [
        _make_conversation("c1", "t1", "user-a", "Q1"),
        _make_conversation("c2", "t1", "user-a", "Q2"),
    ]

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = conversations
    mock_session.execute.return_value = mock_result
    mock_session.scalar.return_value = 2

    mock_request = MagicMock()
    mock_request.headers.get.return_value = "user-a"
    mock_request.state.api_key_name = ""

    response = await list_history(
        request=mock_request,
        limit=20,
        offset=0,
        tenant_id="t1",
        session=mock_session,
    )

    assert response.total == 2
    assert len(response.conversations) == 2
    assert all(c.tenant_id == "t1" for c in response.conversations)

    # Verify the DB query included tenant + user filters
    executed_query = mock_session.execute.call_args_list[-1][0][0]
    compiled = str(executed_query.compile(compile_kwargs={"literal_binds": True}))
    assert "t1" in compiled
    assert "user-a" in compiled


@pytest.mark.asyncio
async def test_history_returns_query_text_and_preview():
    """Each item must include query_text and response_preview from metadata."""
    from src.api.routes.chat import list_history

    conv = _make_conversation("c1", "t1", "u1", "How does X work?")
    conv.metadata_ = {"query": "How does X work?", "answer": "X works by doing Y " * 20}

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [conv]
    mock_session.execute.return_value = mock_result
    mock_session.scalar.return_value = 1

    mock_request = MagicMock()
    mock_request.headers.get.return_value = "u1"
    mock_request.state.api_key_name = ""

    response = await list_history(
        request=mock_request, limit=20, offset=0, tenant_id="t1", session=mock_session
    )

    item = response.conversations[0]
    assert item.query_text == "How does X work?"
    assert item.response_preview is not None
    assert len(item.response_preview) <= 103  # 100 chars + "..."


@pytest.mark.asyncio
async def test_history_missing_user_id_raises_401():
    """If no user identity can be resolved, the endpoint must reject with 401."""
    from fastapi import HTTPException

    from src.api.routes.chat import list_history

    mock_request = MagicMock()
    mock_request.headers.get.return_value = ""
    mock_request.state.api_key_name = ""

    with pytest.raises(HTTPException) as exc_info:
        await list_history(
            request=mock_request, limit=20, offset=0, tenant_id="t1", session=AsyncMock()
        )

    assert exc_info.value.status_code == 401


# =============================================================================
# Issue #72: Admin chat history group attribution by authenticated api_key_id
# =============================================================================


@pytest.mark.asyncio
async def test_admin_list_chat_history_groups_attributed_by_api_key_id(monkeypatch):
    """Admin chat history group attribution must resolve via `api_key_id`, not `user_id`.

    Covers issue #72:
    1. A conversation with `api_key_id="key-1"` and an arbitrary `user_id="user-xyz"`
       is attributed to key-1's group ("Engineering").
    2. A conversation with `api_key_id="key-2"` and `user_id="key-1"` (an X-User-ID
       header colliding with key-1's name) is attributed to key-2's group ("Marketing"),
       NOT key-1's group ("Engineering").
    """
    from types import SimpleNamespace
    from src.api.routes.admin.chat_history import list_chat_history

    conv1 = MagicMock()
    conv1.id = "conv-1"
    conv1.tenant_id = "tenant-a"
    conv1.user_id = "user-xyz"  # arbitrary application user ID
    conv1.api_key_id = "key-1"
    conv1.title = "Query 1"
    conv1.summary = "Summary 1"
    conv1.created_at = datetime(2026, 1, 1)
    conv1.metadata_ = {"query": "Query 1", "answer": "Answer 1", "history": []}

    conv2 = MagicMock()
    conv2.id = "conv-2"
    conv2.tenant_id = "tenant-a"
    conv2.user_id = "key-1"  # X-User-ID header colliding with key-1's name
    conv2.api_key_id = "key-2"
    conv2.title = "Query 2"
    conv2.summary = "Summary 2"
    conv2.created_at = datetime(2026, 1, 2)
    conv2.metadata_ = {"query": "Query 2", "answer": "Answer 2", "history": []}

    mock_session = AsyncMock()

    # 1st execute: ConversationSummaries
    res_convs = MagicMock()
    res_convs.scalars.return_value.all.return_value = [conv2, conv1]

    # 2nd execute: Feedbacks
    res_feedback = MagicMock()
    res_feedback.fetchall.return_value = []

    # 3rd execute: Group lookup SQL (key_id -> group_name)
    res_groups = MagicMock()
    res_groups.fetchall.return_value = [
        SimpleNamespace(key_id="key-1", group_name="Engineering"),
        SimpleNamespace(key_id="key-2", group_name="Marketing"),
    ]

    mock_session.execute.side_effect = [res_convs, res_feedback, res_groups]

    monkeypatch.setattr(
        "src.core.admin_ops.application.metrics.collector.MetricsCollector.get_recent",
        AsyncMock(return_value=[]),
    )

    mock_request = MagicMock()
    mock_request.state.is_super_admin = True
    mock_request.state.tenant_id = "tenant-a"

    res = await list_chat_history(
        request=mock_request,
        limit=20,
        offset=0,
        tenant_id=None,
        session=mock_session,
    )

    assert res.total == 2
    by_id = {c.request_id: c for c in res.conversations}

    # conv1 (api_key_id="key-1", user_id="user-xyz") -> Engineering
    assert by_id["conv-1"].group_name == "Engineering"

    # conv2 (api_key_id="key-2", user_id="key-1") -> Marketing (NOT Engineering!)
    assert by_id["conv-2"].group_name == "Marketing"


@pytest.mark.asyncio
async def test_admin_list_chat_history_legacy_row_yields_no_group(monkeypatch):
    """A legacy row with `api_key_id=None` must yield `group_name=None`,
    even if its `user_id` matches a valid API key name."""
    from types import SimpleNamespace
    from src.api.routes.admin.chat_history import list_chat_history

    conv_legacy = MagicMock()
    conv_legacy.id = "conv-legacy"
    conv_legacy.tenant_id = "tenant-a"
    conv_legacy.user_id = "key-1"  # matches key-1's name, but api_key_id is None
    conv_legacy.api_key_id = None
    conv_legacy.title = "Legacy Query"
    conv_legacy.summary = "Legacy Summary"
    conv_legacy.created_at = datetime(2026, 1, 1)
    conv_legacy.metadata_ = {"query": "Legacy Query", "answer": "Legacy Answer", "history": []}

    mock_session = AsyncMock()

    res_convs = MagicMock()
    res_convs.scalars.return_value.all.return_value = [conv_legacy]

    res_feedback = MagicMock()
    res_feedback.fetchall.return_value = []

    res_groups = MagicMock()
    res_groups.fetchall.return_value = [
        SimpleNamespace(key_id="key-1", group_name="Engineering"),
    ]

    mock_session.execute.side_effect = [res_convs, res_feedback, res_groups]

    monkeypatch.setattr(
        "src.core.admin_ops.application.metrics.collector.MetricsCollector.get_recent",
        AsyncMock(return_value=[]),
    )

    mock_request = MagicMock()
    mock_request.state.is_super_admin = True
    mock_request.state.tenant_id = "tenant-a"

    res = await list_chat_history(
        request=mock_request,
        limit=20,
        offset=0,
        tenant_id=None,
        session=mock_session,
    )

    assert res.total == 1
    assert res.conversations[0].group_name is None
