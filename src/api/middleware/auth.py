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

from src.core.tenants.application.query_scopes import (
    resolve_query_scopes,
    resolve_super_admin_query_scopes,
)
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


def _cors_error_response(
    status_code: int, code: str, message: str, origin: str = "*"
) -> JSONResponse:
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

        api_key = None

        # 1. Try Ticket Auth (Secure SSE)
        ticket = request.query_params.get("ticket")
        is_sse_path = any(p in path for p in ["/stream", "/events"])

        if ticket and is_sse_path:
            from src.core.auth.application.ticket_service import TicketService

            ticket_service = TicketService()
            try:
                # Redeem ticket (consume it)
                api_key = await ticket_service.redeem_ticket(ticket)
                if not api_key:
                    logger.warning(f"Invalid or expired ticket used for {path}")
                    return _cors_error_response(
                        401, "UNAUTHORIZED", "Invalid or expired ticket.", origin
                    )
            except Exception as e:
                logger.error(f"Ticket redemption error: {e}")
                return _cors_error_response(500, "INTERNAL_ERROR", "Auth error", origin)
            finally:
                await ticket_service.close()

        # 2. Try Standard Header Auth
        if not api_key:
            api_key = request.headers.get("X-API-Key")

        if not api_key:
            logger.warning(f"Missing API key for {request.method} {path}")
            return _cors_error_response(
                401,
                "UNAUTHORIZED",
                "Missing API key. Provide X-API-Key header or valid ticket.",
                origin,
            )

        # Resolve settings once (needed later for linkless-key guard)
        from src.api.config import get_settings as _get_settings

        _settings = _get_settings()

        # Validate API key via Service
        from src.api.deps import _get_async_session_maker
        from src.core.admin_ops.application.api_key_service import ApiKeyService

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
            return _cors_error_response(401, "UNAUTHORIZED", "Invalid API key.", origin)

        # Resolve Tenant Context
        header_tenant_id = request.headers.get("X-Tenant-ID")
        allowed_tenants = {t.id for t in valid_key.tenants}
        tenant_id = None

        if header_tenant_id:
            # Client requested specific tenant
            if header_tenant_id in allowed_tenants:
                tenant_id = TenantId(header_tenant_id)
            elif "super_admin" in (valid_key.scopes or []) or "root" in (
                valid_key.scopes or []
            ):  # Allow Super Admin to impersonate any tenant
                tenant_id = TenantId(header_tenant_id)
            elif not allowed_tenants:
                # Legacy/Bootstrap: key has no api_key_tenants links.
                # Gate behind ALLOW_LINKLESS_KEY_DEFAULT_TENANT (default True) so
                # operators can disable this once all keys are properly linked.
                if header_tenant_id == "default" and _settings.allow_linkless_key_default_tenant:
                    logger.warning(
                        "SECURITY: API key '%s' has no tenant links and is falling back to "
                        "the 'default' tenant (legacy bootstrap path). "
                        "Link this key to a tenant or set "
                        "ALLOW_LINKLESS_KEY_DEFAULT_TENANT=false to disable this fallback.",
                        valid_key.name,
                    )
                    tenant_id = TenantId("default")
                else:
                    if header_tenant_id == "default" and not _settings.allow_linkless_key_default_tenant:
                        logger.warning(
                            "SECURITY: API key '%s' attempted linkless default-tenant access "
                            "but ALLOW_LINKLESS_KEY_DEFAULT_TENANT is disabled.",
                            valid_key.name,
                        )
                    else:
                        logger.warning(
                            "Access denied for key '%s' to tenant %s (no tenant links)",
                            valid_key.name,
                            header_tenant_id,
                        )
                    return _cors_error_response(403, "FORBIDDEN", "Access to tenant denied", origin)
            else:
                logger.warning(
                    f"Access denied for key {valid_key.name} to tenant {header_tenant_id}"
                )
                return _cors_error_response(403, "FORBIDDEN", "Access to tenant denied", origin)
        else:
            # No tenant specified
            if len(allowed_tenants) == 1:
                # Ambiguity resolved: exact one match
                tenant_id = TenantId(list(allowed_tenants)[0])
            elif not allowed_tenants:
                # Legacy/Bootstrap: key has no api_key_tenants links; fall back to default.
                # Gate behind ALLOW_LINKLESS_KEY_DEFAULT_TENANT (default True).
                if _settings.allow_linkless_key_default_tenant:
                    logger.warning(
                        "SECURITY: API key '%s' has no tenant links and is falling back to "
                        "the 'default' tenant (legacy bootstrap path). "
                        "Link this key to a tenant or set "
                        "ALLOW_LINKLESS_KEY_DEFAULT_TENANT=false to disable this fallback.",
                        valid_key.name,
                    )
                    tenant_id = TenantId("default")
                else:
                    logger.warning(
                        "SECURITY: API key '%s' has no tenant links and "
                        "ALLOW_LINKLESS_KEY_DEFAULT_TENANT is disabled — rejecting.",
                        valid_key.name,
                    )
                    return _cors_error_response(403, "FORBIDDEN", "Access to tenant denied", origin)
            else:
                # Ambiguous
                return _cors_error_response(
                    400,
                    "BAD_REQUEST",
                    "Multiple tenants available. Specify X-Tenant-ID header.",
                    origin,
                )

        permissions = valid_key.scopes or []

        set_current_tenant(tenant_id)
        set_permissions(permissions)

        # Resolve Tenant Role from the ApiKeyTenant association
        tenant_role = "user"  # Default role
        if str(tenant_id) in allowed_tenants:
            # Find the specific association to get the role
            from src.core.admin_ops.domain.api_key import ApiKeyTenant

            async with _get_async_session_maker()() as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(ApiKeyTenant.role).where(
                        ApiKeyTenant.api_key_id == valid_key.id,
                        ApiKeyTenant.tenant_id == str(tenant_id),
                    )
                )
                role_row = result.scalar_one_or_none()
                if role_row:
                    tenant_role = role_row

        # Store in request state for easy access
        is_super_admin = "super_admin" in permissions

        # Resolve group IDs for this api_key + tenant
        group_ids: list[str] = []
        if not is_super_admin:
            async with _get_async_session_maker()() as _grp_session:
                from sqlalchemy import select

                from src.core.tenants.domain.group import GroupMember

                _grp_result = await _grp_session.execute(
                    select(GroupMember.group_id).where(
                        GroupMember.api_key_id == valid_key.id,
                        GroupMember.tenant_id == str(tenant_id),
                    )
                )
                group_ids = list(_grp_result.scalars().all())

        # Resolve groups_enforced from tenant config
        groups_enforced = False
        if not is_super_admin:
            async with _get_async_session_maker()() as _t_session:
                from sqlalchemy import select

                from src.core.tenants.domain.tenant import Tenant as _Tenant2

                _t_result = await _t_session.execute(
                    select(_Tenant2.config).where(_Tenant2.id == str(tenant_id))
                )
                _t_config = _t_result.scalar_one_or_none() or {}
                groups_enforced = bool(_t_config.get("groups_enforced", False))

        if is_super_admin:
            from sqlalchemy import select as _select

            from src.core.tenants.domain.tenant import Tenant as _Tenant
            async with _get_async_session_maker()() as _sa_session:
                _result = await _sa_session.execute(_select(_Tenant.id))
                all_tenant_ids = list(_result.scalars().all())
            query_scopes = resolve_super_admin_query_scopes(all_tenant_ids)
        else:
            query_scopes = resolve_query_scopes(str(tenant_id))

        request.state.tenant_id = tenant_id
        request.state.query_scopes = query_scopes
        request.state.permissions = permissions
        request.state.api_key_id = valid_key.id
        request.state.api_key_name = valid_key.name
        request.state.api_key_prefix = valid_key.prefix
        request.state.tenant_role = tenant_role
        request.state.is_super_admin = is_super_admin
        request.state.group_ids = group_ids
        request.state.groups_enforced = groups_enforced

        logger.debug(
            f"Authenticated: tenant={tenant_id}, key={valid_key.name}, "
            f"role={tenant_role}, super_admin={request.state.is_super_admin}, "
            f"group_ids={group_ids}, path={request.method} {path}"
        )

        return await call_next(request)
