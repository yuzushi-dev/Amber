"""
Context Variables
==================

Thread-safe context variables for request-scoped data.
Uses Python's contextvars for async-safe context propagation.
"""

from contextvars import ContextVar
from typing import Any

from src.shared.identifiers import RequestId, TenantId

# =============================================================================
# Context Variables
# =============================================================================

# Tenant context - set by auth middleware
_tenant_id: ContextVar[TenantId | None] = ContextVar("tenant_id", default=None)

# Request ID context - set by request ID middleware
_request_id: ContextVar[RequestId | None] = ContextVar("request_id", default=None)

# User permissions context - set by auth middleware
_permissions: ContextVar[list[str]] = ContextVar("permissions", default=[])

# Extra context data - for extensibility
_extra_context: ContextVar[dict[str, Any]] = ContextVar("extra_context", default={})


# =============================================================================
# Tenant Context
# =============================================================================


def get_current_tenant() -> TenantId | None:
    """
    Get the current tenant ID from context.

    Returns:
        TenantId or None: Current tenant ID if set
    """
    return _tenant_id.get()


def set_current_tenant(tenant_id: TenantId | str) -> None:
    """
    Set the current tenant ID in context.

    Args:
        tenant_id: Tenant ID to set
    """
    if isinstance(tenant_id, str):
        tenant_id = TenantId(tenant_id)
    _tenant_id.set(tenant_id)


def require_tenant() -> TenantId:
    """
    Get the current tenant ID, raising if not set.

    Returns:
        TenantId: Current tenant ID

    Raises:
        RuntimeError: If no tenant is set in context
    """
    tenant = get_current_tenant()
    if tenant is None:
        raise RuntimeError("No tenant ID in context. Ensure auth middleware is active.")
    return tenant


# =============================================================================
# Request ID Context
# =============================================================================


def get_request_id() -> RequestId | None:
    """
    Get the current request ID from context.

    Returns:
        RequestId or None: Current request ID if set
    """
    return _request_id.get()


def set_request_id(request_id: RequestId | str) -> None:
    """
    Set the current request ID in context.

    Args:
        request_id: Request ID to set
    """
    if isinstance(request_id, str):
        request_id = RequestId(request_id)
    _request_id.set(request_id)


def require_request_id() -> RequestId:
    """
    Get the current request ID, raising if not set.

    Returns:
        RequestId: Current request ID

    Raises:
        RuntimeError: If no request ID is set in context
    """
    request_id = get_request_id()
    if request_id is None:
        raise RuntimeError("No request ID in context. Ensure request_id middleware is active.")
    return request_id


# =============================================================================
# Permissions Context
# =============================================================================


def get_permissions() -> list[str]:
    """
    Get the current user's permissions from context.

    Returns:
        list[str]: List of permission strings
    """
    return _permissions.get()


def set_permissions(permissions: list[str]) -> None:
    """
    Set the current user's permissions in context.

    Args:
        permissions: List of permission strings
    """
    _permissions.set(permissions)


def has_permission(permission: str) -> bool:
    """
    Check if the current user has a specific permission.

    Args:
        permission: Permission to check

    Returns:
        bool: True if user has the permission
    """
    return permission in get_permissions()


def require_permission(permission: str) -> None:
    """
    Require a specific permission, raising if not present.

    Args:
        permission: Permission to require

    Raises:
        PermissionError: If user lacks the permission
    """
    if not has_permission(permission):
        raise PermissionError(f"Permission denied: {permission}")


# =============================================================================
# Extra Context
# =============================================================================


def get_extra_context() -> dict[str, Any]:
    """
    Get extra context data.

    Returns:
        dict: Extra context data
    """
    return _extra_context.get()


def set_extra_context(data: dict[str, Any]) -> None:
    """
    Set extra context data.

    Args:
        data: Context data to set
    """
    _extra_context.set(data)


def add_to_context(key: str, value: Any) -> None:
    """
    Add a value to extra context.

    Args:
        key: Context key
        value: Context value
    """
    ctx = get_extra_context().copy()
    ctx[key] = value
    _extra_context.set(ctx)
