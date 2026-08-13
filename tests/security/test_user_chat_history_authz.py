"""Regression tests for authenticated ownership of user chat history."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


def _request(user_id: str, api_key_id: str | None):
    return SimpleNamespace(
        headers={"X-User-ID": user_id},
        state=SimpleNamespace(api_key_id=api_key_id, api_key_name="shared-key"),
    )


def _session(rows=None):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows or []
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    session.scalar.return_value = 0
    return session


def _compiled_query(session) -> str:
    statement = session.execute.call_args.args[0]
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_list_history_uses_authenticated_api_key_not_spoofable_header():
    from src.api.routes.chat import list_history

    session = _session()
    response = await list_history(
        request=_request("victim-user", "key-attacker"),
        limit=20,
        offset=0,
        tenant_id="tenant-a",
        session=session,
    )

    assert response.total == 0
    query = _compiled_query(session)
    assert "api_key_id = 'key-attacker'" in query
    assert "victim-user" not in query


@pytest.mark.asyncio
async def test_list_history_same_api_key_has_one_explicit_owner():
    from src.api.routes.chat import list_history

    queries = []
    for user_id in ("alice", "bob"):
        session = _session()
        await list_history(
            request=_request(user_id, "key-shared"),
            limit=20,
            offset=0,
            tenant_id="tenant-a",
            session=session,
        )
        queries.append(_compiled_query(session))

    assert all("api_key_id = 'key-shared'" in query for query in queries)
    assert "alice" not in queries[0] and "bob" not in queries[0]
    assert "alice" not in queries[1] and "bob" not in queries[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["detail", "delete"])
async def test_detail_and_delete_history_use_the_same_authenticated_owner(operation):
    from src.api.routes.chat import delete_history, get_history_detail

    session = _session()
    handler = get_history_detail if operation == "detail" else delete_history

    with pytest.raises(HTTPException) as exc_info:
        await handler(
            conversation_id="conversation-victim",
            request=_request("victim-user", "key-attacker"),
            tenant_id="tenant-a",
            session=session,
        )

    assert exc_info.value.status_code == 404
    query = _compiled_query(session)
    assert "api_key_id = 'key-attacker'" in query
    assert "victim-user" not in query


@pytest.mark.asyncio
async def test_history_rejects_missing_authenticated_principal_even_with_header():
    from src.api.routes.chat import list_history

    with pytest.raises(HTTPException) as exc_info:
        await list_history(
            request=_request("victim-user", None),
            limit=20,
            offset=0,
            tenant_id="tenant-a",
            session=_session(),
        )

    assert exc_info.value.status_code == 401
