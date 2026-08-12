"""
API Dependencies
================

FastAPI dependency injection utilities.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

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


@dataclass(frozen=True)
class RequestRlsContext:
    """The complete RLS state that must be applied to every request DB session."""

    tenant_id: str
    is_super_admin: bool
    group_ids: tuple[str, ...]
    tenant_role: str | None
    groups_enforced: bool


def get_request_rls_context(request: Request) -> RequestRlsContext:
    """Snapshot the request state used by PostgreSQL row-level security."""
    from src.shared.context import get_current_tenant

    tenant_id = getattr(request.state, "tenant_id", None) or get_current_tenant()
    permissions = getattr(request.state, "permissions", [])
    group_ids = getattr(request.state, "group_ids", [])

    return RequestRlsContext(
        tenant_id=str(tenant_id) if tenant_id else "",
        is_super_admin="super_admin" in permissions,
        group_ids=tuple(group_ids),
        tenant_role=getattr(request.state, "tenant_role", "user"),
        groups_enforced=bool(getattr(request.state, "groups_enforced", False)),
    )


async def apply_request_rls_context(session: AsyncSession, context: RequestRlsContext) -> None:
    """Apply every request RLS GUC unconditionally to one fresh session."""
    from sqlalchemy import text

    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
        {"tenant_id": context.tenant_id},
    )
    await session.execute(
        text("SELECT set_config('app.is_super_admin', :is_super, false)"),
        {"is_super": "true" if context.is_super_admin else "false"},
    )
    await session.execute(
        text("SELECT set_config('app.current_groups', :groups, false)"),
        {"groups": ",".join(context.group_ids)},
    )
    await session.execute(
        text("SELECT set_config('app.tenant_role', :role, false)"),
        {"role": context.tenant_role},
    )
    await session.execute(
        text("SELECT set_config('app.groups_enforced', :enforced, false)"),
        {"enforced": "true" if context.groups_enforced else "false"},
    )


@asynccontextmanager
async def request_rls_session(context: RequestRlsContext) -> AsyncIterator[AsyncSession]:
    """Open, configure, commit/rollback, and close one request-RLS session."""
    session_maker = _get_async_session_maker()
    async with session_maker() as session:
        try:
            await apply_request_rls_context(session, context)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that yields a database session.

    Injects the current tenant ID into the session for RLS.
    Sets app.is_super_admin if the user has the 'super_admin' scope.
    """
    context = get_request_rls_context(request)
    async with request_rls_session(context) as session:
        yield session


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

    Scopes are resolved by AuthMiddleware and stored in request.state.
    Super-admin requests cover all tenants; regular requests cover own tenant + default.
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


async def verify_group_admin(request: Request):
    """
    Dependency to verify group management privileges.

    Allows access if ANY of the following is true:
    - The caller is a super-admin (platform-wide access).
    - The caller holds the global 'admin' scope (existing prod admin keys).
    - The caller has the per-tenant 'admin' role.

    This union gate ensures no class of admin is locked out of group management.
    """
    if getattr(request.state, "is_super_admin", False):
        return  # Super Admin has all rights

    permissions = getattr(request.state, "permissions", [])
    if "admin" in permissions:
        return  # Global admin scope

    tenant_role = getattr(request.state, "tenant_role", None)
    if tenant_role == "admin":
        return  # Per-tenant admin role

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin privileges required to manage groups",
    )
