"""
Rate Limiting Middleware
========================

Enforces rate limits per tenant using Redis.
"""

import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.api.config import settings
from src.core.rate_limiter import RateLimitCategory, rate_limiter
from src.shared.context import get_current_tenant

logger = logging.getLogger(__name__)

# Path patterns for different rate limit categories
QUERY_PATHS = {"/v1/query", "/v1/chat"}
UPLOAD_PATHS = {"/v1/documents"}

# Paths excluded from rate limiting
EXCLUDED_PATHS = {
    "/health",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _get_category(path: str, method: str) -> RateLimitCategory | None:
    """Determine rate limit category for a request."""
    # Skip excluded paths
    if path in EXCLUDED_PATHS or path.startswith("/docs"):
        return None

    # Determine category based on path
    if path in QUERY_PATHS or path.startswith("/v1/query"):
        return RateLimitCategory.QUERY
    elif path in UPLOAD_PATHS and method == "POST":
        return RateLimitCategory.UPLOAD
    else:
        return RateLimitCategory.GENERAL


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for enforcing rate limits.

    Applies per-tenant rate limits using Redis-backed sliding window.
    Returns 429 Too Many Requests when limits are exceeded.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request through rate limiting."""
        path = request.url.path
        method = request.method

        # Determine rate limit category
        category = _get_category(path, method)
        if category is None:
            return await call_next(request)

        # Get tenant ID (set by auth middleware)
        tenant_id = get_current_tenant()
        if tenant_id is None:
            # If no tenant (before auth), use a default
            tenant_id = "anonymous"

        # Check rate limit
        result = await rate_limiter.check(str(tenant_id), category)

        if not result.allowed:
            logger.warning(
                f"Rate limit exceeded: tenant={tenant_id}, category={category.value}, "
                f"path={method} {path}"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Too many requests. Please retry after {result.retry_after} seconds.",
                        "retry_after": result.retry_after,
                    }
                },
                headers={
                    "Retry-After": str(result.retry_after),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_at),
                },
            )

        # Proceed with request
        response = await call_next(request)

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_at)

        return response


class UploadSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for enforcing upload size limits.

    Checks Content-Length header and rejects oversized requests.
    Returns 413 Payload Too Large when exceeded.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request through size limiting."""
        # Only check POST/PUT requests
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size_bytes = int(content_length)
                max_bytes = settings.uploads.max_size_mb * 1024 * 1024

                if size_bytes > max_bytes:
                    logger.warning(
                        f"Upload too large: {size_bytes} bytes > {max_bytes} bytes "
                        f"(path={request.method} {request.url.path})"
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": f"Upload exceeds maximum size of {settings.uploads.max_size_mb}MB",
                                "max_size_mb": settings.uploads.max_size_mb,
                                "received_mb": round(size_bytes / (1024 * 1024), 2),
                            }
                        },
                    )
            except ValueError:
                pass  # Invalid content-length, let FastAPI handle it

        return await call_next(request)
