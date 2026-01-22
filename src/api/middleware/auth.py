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
from src.shared.security import mask_api_key

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/health/ready",
    "/v1/health",
    "/v1/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _is_public_path(path: str) -> bool:
    """Check if a path is public (doesn't require auth)."""
    # Exact matches
    if path in PUBLIC_PATHS:
        return True
    # Prefix matches for documentation paths
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    # Health checks under /v1 or /api
    if path.startswith("/v1/health") or path.startswith("/api/health"):
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

        # Validate API key via Service
        from src.api.deps import _get_async_session_maker
        from src.core.services.api_key_service import ApiKeyService

        valid_key = None
        try:
            async with _get_async_session_maker()() as session:
                service = ApiKeyService(session)
                valid_key = await service.validate_key(api_key)
        except Exception as e:
            logger.error(f"Auth DB Error: {e}")
            return _cors_error_response(500, "INTERNAL_ERROR", "Authentication failed", origin)

        if not valid_key:
            logger.warning(f"Invalid API key {mask_api_key(api_key)} for {request.method} {path}")
            return _cors_error_response(
                401,
                "UNAUTHORIZED",
                "Invalid API key.",
                origin
            )

        # Resolve Tenant Context
        header_tenant_id = request.headers.get("X-Tenant-ID")
        allowed_tenants = {t.id for t in valid_key.tenants}
        tenant_id = None

        if header_tenant_id:
            # Client requested specific tenant
            if header_tenant_id in allowed_tenants:
                tenant_id = TenantId(header_tenant_id)
            elif not allowed_tenants:
                 # Legacy/Bootstrap: If key has no specific links, allow 'default' if requested
                 # This ensures unmigrated keys still work for default tenant
                 if header_tenant_id == "default":
                     tenant_id = TenantId("default")
                 else:
                     logger.warning(f"Access denied for key {valid_key.name} to tenant {header_tenant_id} (No links)")
                     return _cors_error_response(403, "FORBIDDEN", "Access to tenant denied", origin)
            else:
                logger.warning(f"Access denied for key {valid_key.name} to tenant {header_tenant_id}")
                return _cors_error_response(403, "FORBIDDEN", "Access to tenant denied", origin)
        else:
            # No tenant specified
            if len(allowed_tenants) == 1:
                # Ambiguity resolved: exact one match
                tenant_id = TenantId(list(allowed_tenants)[0])
            elif not allowed_tenants:
                # Fallback to default
                tenant_id = TenantId("default")
            else:
                # Ambiguous
                return _cors_error_response(
                    400,
                    "BAD_REQUEST",
                    "Multiple tenants available. Specify X-Tenant-ID header.",
                    origin
                )

        permissions = valid_key.scopes or []

        set_current_tenant(tenant_id)
        set_permissions(permissions)

        # Resolve Tenant Role from the ApiKeyTenant association
        tenant_role = "user"  # Default role
        if str(tenant_id) in allowed_tenants:
            # Find the specific association to get the role
            from src.core.models.api_key import ApiKeyTenant
            async with _get_async_session_maker()() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(ApiKeyTenant.role).where(
                        ApiKeyTenant.api_key_id == valid_key.id,
                        ApiKeyTenant.tenant_id == str(tenant_id)
                    )
                )
                role_row = result.scalar_one_or_none()
                if role_row:
                    tenant_role = role_row

        # Store in request state for easy access
        request.state.tenant_id = tenant_id
        request.state.permissions = permissions
        request.state.api_key_name = valid_key.name
        request.state.tenant_role = tenant_role
        request.state.is_super_admin = "super_admin" in permissions

        logger.debug(
            f"Authenticated: tenant={tenant_id}, key={valid_key.name}, "
            f"role={tenant_role}, super_admin={request.state.is_super_admin}, "
            f"path={request.method} {path}"
        )

        return await call_next(request)
