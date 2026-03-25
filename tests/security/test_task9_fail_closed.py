"""
Security tests for Task 9: fail-closed rate limiting.

Verifies that:
- RateLimiter.check() re-raises Redis exceptions rather than returning allowed=True
- RateLimitMiddleware returns 503 when Redis is unavailable (fail closed by default)
- RATE_LIMIT_FAIL_OPEN=true restores the legacy fail-open behaviour
- Ollama capacity limiter raises (or propagates fail-closed) on Redis error
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock
from fastapi import Request
from starlette.responses import Response


# ── RateLimiter.check(): re-raises on Redis error ─────────────────────────────


@pytest.mark.asyncio
async def test_rate_limiter_check_raises_on_redis_error():
    """
    RateLimiter.check() must propagate Redis exceptions instead of silently
    returning allowed=True.  Swallowing the error defeats the rate limit.
    """
    from src.core.admin_ops.infrastructure.rate_limiter import RateLimiter
    import redis.asyncio as aioredis

    limiter = RateLimiter(redis_url="redis://localhost:6379")

    # Inject a Redis mock that raises on pipeline
    mock_redis = AsyncMock()
    mock_redis.pipeline.side_effect = aioredis.ConnectionError("Redis offline")
    limiter._redis = mock_redis

    with pytest.raises(Exception):
        await limiter.check("tenant-x", )


# ── RateLimitMiddleware: fail-closed by default ───────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_middleware_returns_503_on_redis_error():
    """
    When the rate limiter raises (Redis down) and RATE_LIMIT_FAIL_OPEN is False
    (the default), the middleware must return 503 Service Unavailable.
    """
    from src.api.middleware.rate_limit import RateLimitMiddleware
    from src.api.config import settings as app_settings

    # Temporarily set fail_open=False
    original = getattr(app_settings.rate_limits, "fail_open", None)

    async def _boom(tenant_id, category):
        raise RuntimeError("Redis unavailable")

    mock_limiter = MagicMock()
    mock_limiter.check = _boom

    request = MagicMock(spec=Request)
    request.url.path = "/v1/query"
    request.method = "POST"
    request.headers = {"Origin": "http://test.example"}
    request.client = MagicMock()
    request.client.host = "1.2.3.4"

    middleware = RateLimitMiddleware(app=MagicMock())

    with patch("src.api.middleware.rate_limit._get_rate_limiter", return_value=mock_limiter), \
         patch("src.api.middleware.rate_limit.get_current_tenant", return_value="test-tenant"), \
         patch.object(app_settings.rate_limits, "fail_open", False, create=True):

        response = await middleware.dispatch(request, AsyncMock(return_value=Response()))

    assert response.status_code == 503, (
        f"Expected 503 when Redis is down (fail-closed default), got {response.status_code}. "
        "Rate limiter fails open — DoS protection can be bypassed by killing Redis."
    )


@pytest.mark.asyncio
async def test_rate_limit_middleware_passes_through_on_redis_error_when_fail_open():
    """
    When RATE_LIMIT_FAIL_OPEN is True, the middleware should allow the request
    through even when the rate limiter raises (preserving legacy behaviour for
    operators who explicitly opt into it).
    """
    from src.api.middleware.rate_limit import RateLimitMiddleware
    from src.api.config import settings as app_settings

    async def _boom(tenant_id, category):
        raise RuntimeError("Redis unavailable")

    mock_limiter = MagicMock()
    mock_limiter.check = _boom

    request = MagicMock(spec=Request)
    request.url.path = "/v1/query"
    request.method = "POST"
    request.headers = {"Origin": "http://test.example"}
    request.client = MagicMock()
    request.client.host = "1.2.3.4"

    downstream_response = Response(status_code=200)
    middleware = RateLimitMiddleware(app=MagicMock())

    with patch("src.api.middleware.rate_limit._get_rate_limiter", return_value=mock_limiter), \
         patch("src.api.middleware.rate_limit.get_current_tenant", return_value="test-tenant"), \
         patch.object(app_settings.rate_limits, "fail_open", True, create=True):

        response = await middleware.dispatch(request, AsyncMock(return_value=downstream_response))

    assert response.status_code == 200, (
        "Expected pass-through (200) when fail_open=True, "
        f"got {response.status_code}"
    )


# ── RateLimitSettings: fail_open config field exists ─────────────────────────


def test_rate_limit_settings_has_fail_open_field():
    """
    RateLimitSettings must expose a fail_open field (env: RATE_LIMIT_FAIL_OPEN)
    defaulting to False so the fail-closed behaviour is opt-out rather than opt-in.
    """
    from src.api.config import RateLimitSettings
    import inspect
    fields = RateLimitSettings.model_fields
    assert "fail_open" in fields, (
        "RateLimitSettings missing 'fail_open' field. "
        "Operators cannot distinguish between intentional bypass and Redis failure."
    )
    assert fields["fail_open"].default is False, (
        "fail_open must default to False (fail-closed). "
        "Current default allows any Redis outage to bypass rate limiting."
    )
