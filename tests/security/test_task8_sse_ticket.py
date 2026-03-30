"""
Security tests for Task 8: SSE ticket one-time use.

Verifies that:
- redeem_ticket() deletes the ticket from Redis after first use (GETDEL)
- A second redemption of the same ticket returns None
- redeem_ticket() for non-existent ticket returns None
- Source code no longer uses bare client.get() without delete
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_service(mock_redis):
    """Build a TicketService with mocked settings and a given redis client."""
    from src.core.auth.application.ticket_service import TicketService
    with patch("src.core.auth.application.ticket_service.get_settings", return_value=MagicMock()):
        svc = TicketService(redis_client=mock_redis)
    return svc


@pytest.mark.asyncio
async def test_redeem_ticket_deletes_on_first_use():
    """
    After a successful redemption, the ticket must be removed from Redis
    so it cannot be replayed within the TTL window.
    """
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value="sk-test-api-key")

    svc = _make_service(mock_redis)
    result = await svc.redeem_ticket("some-token-abc")

    assert result == "sk-test-api-key", "Expected API key back from valid ticket"
    mock_redis.getdel.assert_called_once()
    call_key = mock_redis.getdel.call_args[0][0]
    assert call_key == "auth:ticket:some-token-abc", (
        f"getdel called with wrong key: {call_key!r}"
    )


@pytest.mark.asyncio
async def test_redeem_ticket_returns_none_on_second_use():
    """
    Redeeming the same ticket a second time must return None — the ticket
    is consumed on first use.
    """
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(side_effect=["sk-test-api-key", None])

    svc = _make_service(mock_redis)

    first = await svc.redeem_ticket("replay-token")
    second = await svc.redeem_ticket("replay-token")

    assert first == "sk-test-api-key", "First redemption should succeed"
    assert second is None, (
        "Second redemption returned a value — ticket is replayable within TTL window. "
        "An attacker who intercepts an SSE URL can replay it for up to 30 seconds."
    )


@pytest.mark.asyncio
async def test_redeem_ticket_returns_none_for_missing_ticket():
    """
    Redeeming a non-existent or already-expired ticket must return None.
    """
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value=None)

    svc = _make_service(mock_redis)
    result = await svc.redeem_ticket("no-such-ticket")

    assert result is None


def test_redeem_ticket_does_not_use_bare_get():
    """
    redeem_ticket() must not call client.get() (without delete).
    A bare GET without subsequent DELETE leaves the ticket replayable.
    """
    import inspect

    from src.core.auth.application import ticket_service as ts_module
    source = inspect.getsource(ts_module.TicketService.redeem_ticket)
    assert "await client.get(" not in source, (
        "redeem_ticket() uses bare GET without DELETE. "
        "Replace with atomic GETDEL to prevent ticket replay within the TTL window."
    )
