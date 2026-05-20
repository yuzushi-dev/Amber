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
