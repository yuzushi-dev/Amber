"""
Security tests for Task 3: control-plane route lockdown.

Covers:
- RAGAS routes require super_admin, not just admin
- API key creation cannot escalate to super_admin/root scopes
- Health /ready endpoint does not expose internal error strings
- Setup _check_db_migration_status uses correct import path
"""

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch


# ── RAGAS: super_admin guard ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ragas_stats_requires_super_admin():
    """GET /admin/ragas/stats must reject callers with only 'admin' scope."""
    from src.api.deps import verify_super_admin

    request = MagicMock()
    request.state.is_super_admin = False

    with pytest.raises(HTTPException) as exc_info:
        await verify_super_admin(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_ragas_router_dependency_is_super_admin():
    """The RAGAS router's router-level dependency must be verify_super_admin."""
    from src.api.routes.admin.ragas import router

    # Inspect the router-level dependencies
    dep_functions = [d.dependency for d in router.dependencies]
    dep_names = [getattr(f, "__name__", repr(f)) for f in dep_functions]
    assert "verify_super_admin" in dep_names, (
        f"RAGAS router uses {dep_names!r} instead of verify_super_admin. "
        "Any admin can reach RAGAS benchmark triggers."
    )


# ── API key scope escalation prevention ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_key_rejects_super_admin_scope_for_non_super_admin():
    """An admin-scoped caller must not be able to create a key with super_admin scope."""
    from src.api.routes.admin.keys import CreateKeyRequest, create_api_key

    request = MagicMock()
    # Caller is admin but NOT super_admin
    request.state.permissions = ["admin", "active_user"]
    request.state.is_super_admin = False

    payload = CreateKeyRequest(
        name="escalation-attempt",
        scopes=["admin", "super_admin"],
    )

    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await create_api_key(payload, mock_session, request)
    assert exc_info.value.status_code == 403, (
        f"Expected 403, got {exc_info.value.status_code}. "
        "Admin caller escalated to super_admin scope."
    )


@pytest.mark.asyncio
async def test_create_key_rejects_root_scope_for_non_super_admin():
    """An admin-scoped caller must not be able to create a key with root scope."""
    from src.api.routes.admin.keys import CreateKeyRequest, create_api_key

    request = MagicMock()
    request.state.permissions = ["admin", "active_user"]
    request.state.is_super_admin = False

    payload = CreateKeyRequest(
        name="root-escalation-attempt",
        scopes=["admin", "root"],
    )

    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await create_api_key(payload, mock_session, request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_key_allows_super_admin_scope_for_super_admin():
    """A super_admin caller should be allowed to create super_admin-scoped keys."""
    from src.api.routes.admin.keys import CreateKeyRequest, create_api_key

    request = MagicMock()
    request.state.permissions = ["admin", "super_admin", "root"]
    request.state.is_super_admin = True

    payload = CreateKeyRequest(
        name="valid-super-admin-key",
        scopes=["admin", "super_admin"],
    )

    mock_session = AsyncMock()
    mock_service = AsyncMock()
    mock_service.create_key.return_value = {
        "id": "test-id",
        "name": "valid-super-admin-key",
        "prefix": "amber",
        "scopes": ["admin", "super_admin"],
        "key": "amber_test_key_1234",
        "created_at": __import__("datetime").datetime.now(),
    }

    with patch("src.api.routes.admin.keys.ApiKeyService", return_value=mock_service):
        result = await create_api_key(payload, mock_session, request)
    # Should succeed (no exception)
    assert result is not None


@pytest.mark.asyncio
async def test_update_key_rejects_super_admin_scope_for_non_super_admin():
    """An admin caller must not be able to patch a key to add super_admin scope."""
    from src.api.routes.admin.keys import UpdateKeyRequest, update_api_key

    request = MagicMock()
    request.state.permissions = ["admin"]
    request.state.is_super_admin = False

    payload = UpdateKeyRequest(scopes=["admin", "super_admin"])
    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await update_api_key("some-key-id", payload, mock_session, request)
    assert exc_info.value.status_code == 403


# ── Health endpoint: no internal error leakage ───────────────────────────────


@pytest.mark.asyncio
async def test_health_ready_error_field_is_sanitized():
    """
    When /health/ready encounters a database error, the error field in the
    response must not contain the raw exception message (which could leak
    connection strings, hostnames, or credentials).
    """
    from src.api.routes.health import readiness

    internal_msg = "could not connect to server: Connection refused to db-host.internal:5432"

    with patch(
        "src.api.routes.health._get_health_checker"
    ) as mock_factory:
        mock_checker = AsyncMock()
        mock_checker.check_all.side_effect = Exception(internal_msg)
        mock_factory.return_value = mock_checker

        response = await readiness(silent=True)

    # The response must come back as a model with dependencies
    response_dict = response.model_dump() if hasattr(response, "model_dump") else {}
    for dep_name, dep_status in response_dict.get("dependencies", {}).items():
        error_val = dep_status.get("error") if isinstance(dep_status, dict) else getattr(dep_status, "error", None)
        if error_val:
            assert internal_msg not in error_val, (
                f"Health endpoint leaks internal error in dependency '{dep_name}': {error_val!r}"
            )


# ── Setup: broken import is fixed ────────────────────────────────────────────


def test_setup_check_db_migration_import_is_correct():
    """_check_db_migration_status must import from src.api.config, not api.config."""
    import inspect
    from src.api.routes import setup as setup_module

    source = inspect.getsource(setup_module._check_db_migration_status)
    assert "from api.config" not in source, (
        "_check_db_migration_status still uses broken 'from api.config' import "
        "(missing 'src.' prefix — will fail at runtime)."
    )
    assert "from src.api.config" in source or "settings" in source, (
        "_check_db_migration_status must use src.api.config.settings"
    )
