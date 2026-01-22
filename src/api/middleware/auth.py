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
        from src.api.deps import _async_session_maker
        from src.core.services.api_key_service import ApiKeyService
        from sqlalchemy import select
        from src.core.models.api_key import ApiKeyTenant

        tenant_id = None
        permissions = []
        tenant_role = "user"
        valid_key = None

        try:
            async with _async_session_maker() as session:
                service = ApiKeyService(session)
                valid_key = await service.validate_key(api_key)

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
                # We need to access tenants. Since we are in the session, we can ensure they are loaded
                # But valid_key.tenants is lazy="selectin", so it shoould be fine.
                # Ideally, we query ApiKeyTenant table directly to avoid loading all Tenant objects if there are many.
                # But for now, using the relationship is fine as per existing code.
                allowed_tenants = {t.id for t in valid_key.tenants}
                
                if header_tenant_id:
                    # Client requested specific tenant
                    if header_tenant_id in allowed_tenants:
                        tenant_id = TenantId(header_tenant_id)
                    elif not allowed_tenants:
                         # Legacy/Bootstrap: If key has no specific links, allow 'default' if requested
                         if header_tenant_id == "default":
                             tenant_id = TenantId("default")
                             # Legacy fallback often implies admin for the bootstrap key
                             # But let's check if there is an actual link first
                         else:
                             logger.warning(f"Access denied for key {valid_key.name} to tenant {header_tenant_id} (No links)")
                             return _cors_error_response(403, "FORBIDDEN", "Access to tenant denied", origin)
                    else:
                        logger.warning(f"Access denied for key {valid_key.name} to tenant {header_tenant_id}")
                        return _cors_error_response(403, "FORBIDDEN", "Access to tenant denied", origin)
                else:
                    # No tenant specified
                    if len(allowed_tenants) == 1:
                        tenant_id = TenantId(list(allowed_tenants)[0])
                    elif not allowed_tenants:
                        tenant_id = TenantId("default")
                    else:
                        return _cors_error_response(
                            400,
                            "BAD_REQUEST",
                            "Multiple tenants available. Specify X-Tenant-ID header.",
                            origin
                        )

                # Fetch Role for this specific Token <-> Tenant pair
                # If we fell back to 'default' and no link exists, we might need a default role.
                query = select(ApiKeyTenant.role).where(
                    ApiKeyTenant.api_key_id == valid_key.id,
                    ApiKeyTenant.tenant_id == str(tenant_id)
                )
                result = await session.execute(query)
                fetched_role = result.scalar_one_or_none()
                
                if fetched_role:
                    tenant_role = fetched_role
                else:
                    # If no link exists (legacy/bootstrap fallback), check scopes
                    if "super_admin" in valid_key.scopes:
                        tenant_role = "admin"
                    else:
                        tenant_role = "user"
                
                permissions = valid_key.scopes or []

        except Exception as e:
            logger.error(f"Auth DB Error: {e}")
            return _cors_error_response(500, "INTERNAL_ERROR", "Authentication failed", origin)

        set_current_tenant(tenant_id)
        set_permissions(permissions)

        # Store in request state for easy access
        request.state.tenant_id = tenant_id
        request.state.permissions = permissions
        request.state.api_key_name = valid_key.name
        request.state.api_key_id = valid_key.id
        request.state.tenant_role = tenant_role
        
        # Helper bools
        request.state.is_super_admin = "super_admin" in permissions

        logger.debug(
            f"Authenticated: tenant={tenant_id}, role={tenant_role}, key={valid_key.name}, "
            f"path={request.method} {path}"
        )

        return await call_next(request)
