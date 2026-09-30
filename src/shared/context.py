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
_permissions: ContextVar[list[str]] = ContextVar("permissions", default=None)

# Extra context data - for extensibility
_extra_context: ContextVar[dict[str, Any]] = ContextVar("extra_context", default=None)


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
    Set extra context data (replaces any previous value).

    Args:
        data: Extra context data
    """
    _extra_context.set(data)
