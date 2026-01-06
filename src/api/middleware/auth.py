"""
Authentication Middleware
=========================

API key validation and tenant context injection.
"""

import logging
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.shared.context import set_current_tenant, set_permissions
from src.shared.identifiers import TenantId
from src.shared.security import lookup_api_key, mask_api_key

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/setup/status",
    "/api/setup/install",
    "/api/setup/skip",
    "/api/setup/check-required",
}


def _is_public_path(path: str) -> bool:
    """Check if a path is public (doesn't require auth)."""
    # Exact matches
    if path in PUBLIC_PATHS:
        return True
    # Prefix matches for documentation paths
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    # Setup paths are public
    if path.startswith("/api/setup"):
        return True
    # Health checks under /api
    if path.startswith("/api/health"):
        return True
    return False


def _cors_error_response(status_code: int, code: str, message: str, origin: str = "*") -> JSONResponse:
    """Create a JSONResponse with CORS headers for error responses."""
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )
    # Add CORS headers so browser can read the error
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for API key authentication.

    Validates the X-API-Key header and sets tenant context.
    Public paths bypass authentication.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request through authentication."""
        path = request.url.path
        origin = request.headers.get("Origin", "*")

        # Allow CORS preflight requests through without auth
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for public paths
        if _is_public_path(path):
            return await call_next(request)

        # Extract API key from header
        api_key = request.headers.get("X-API-Key")

        # Fallback: For SSE endpoints, check query params since EventSource can't set headers
        is_sse_path = any(p in path for p in ["/stream", "/events"])
        if not api_key and is_sse_path:
            api_key = request.query_params.get("api_key")

        if not api_key:
            logger.warning(f"Missing API key for {request.method} {path}")
            return _cors_error_response(
                401,
                "UNAUTHORIZED",
                "Missing API key. Provide X-API-Key header.",
                origin
            )

        # Look up the API key
        key_metadata = lookup_api_key(api_key)

        if not key_metadata:
            logger.warning(f"Invalid API key {mask_api_key(api_key)} for {request.method} {path}")
            return _cors_error_response(
                401,
                "UNAUTHORIZED",
                "Invalid API key.",
                origin
            )

        # Set context variables
        tenant_id = TenantId(key_metadata.get("tenant_id", "default"))
        permissions = key_metadata.get("permissions", [])

        set_current_tenant(tenant_id)
        set_permissions(permissions)

        # Store in request state for easy access
        request.state.tenant_id = tenant_id
        request.state.permissions = permissions
        request.state.api_key_name = key_metadata.get("name", "Unknown")

        logger.debug(
            f"Authenticated: tenant={tenant_id}, key={key_metadata.get('name')}, "
            f"path={request.method} {path}"
        )

        return await call_next(request)
