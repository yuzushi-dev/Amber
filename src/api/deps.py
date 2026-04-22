"""
API Dependencies
================

FastAPI dependency injection utilities.
"""

from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession


def _get_session_maker():
    """Get the canonical session maker from the core database module."""
    from src.core.database.session import get_session_maker

    return get_session_maker()


# Backward compatibility: expose _async_session_maker for existing code
# TODO: Remove after Phase 3 when all usages are migrated to UoW
_async_session_maker = None


def _get_async_session_maker():
    """Lazy accessor for backward compatibility."""
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = _get_session_maker()
    return _async_session_maker


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that yields a database session.

    Injects the current tenant ID into the session for RLS.
    Sets app.is_super_admin if the user has the 'super_admin' scope.
    """
    session_maker = _get_async_session_maker()
    async with session_maker() as session:
        try:
            # Inject current tenant into session configuration
            from sqlalchemy import text

            from src.shared.context import get_current_tenant

            tenant_id = get_current_tenant()
            # Always set app.current_tenant, even to an empty string when no
            # tenant is bound to this request. RLS policies on tenant tables
            # read this GUC unconditionally (`current_setting('app.current_tenant')`
            # without missing_ok), so failing to set it raises
            # `unrecognized configuration parameter` 42704 on the first query.
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(tenant_id) if tenant_id else ""},
            )

            # Check for super admin privilege from request state
            permissions = getattr(request.state, "permissions", [])
            if "super_admin" in permissions:
                await session.execute(
                    text("SELECT set_config('app.is_super_admin', 'true', false)")
                )

            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def verify_admin(request: Request):
    """
    Dependency to verify admin privileges.
    """
    # Check permissions from request state (set by AuthMiddleware)
    permissions = getattr(request.state, "permissions", [])

    if "admin" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )


def get_current_tenant_id(request: Request) -> str:
    """
    Dependency to retrieve the current tenant ID.
    Derived from request state set by AuthenticationMiddleware.
    """
    return str(getattr(request.state, "tenant_id", "default"))


def get_query_scopes(request: Request):
    """
    Dependency to retrieve the resolved query scopes for the current request.
    """
    from src.core.tenants.application.query_scopes import resolve_query_scopes

    scopes = getattr(request.state, "query_scopes", None)
    if scopes is not None:
        return scopes

    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: tenant context missing.",
        )

    scopes = resolve_query_scopes(str(tenant_id))
    request.state.query_scopes = scopes
    return scopes


async def verify_super_admin(request: Request):
    """
    Dependency to verify Super Admin privileges.

    Super Admins have platform-wide access and can manage tenants,
    global configuration, and perform cross-tenant operations.
    """
    is_super_admin = getattr(request.state, "is_super_admin", False)

    if not is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin privileges required"
        )


async def verify_tenant_admin(request: Request):
    """
    Dependency to verify Tenant Admin privileges.

    Tenant Admins can manage users and settings within their assigned tenant.
    Super Admins implicitly have Tenant Admin privileges.
    """
    is_super_admin = getattr(request.state, "is_super_admin", False)
    tenant_role = getattr(request.state, "tenant_role", None)

    if is_super_admin:
        return  # Super Admin has all Tenant Admin rights

    if tenant_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Tenant Admin privileges required"
        )
