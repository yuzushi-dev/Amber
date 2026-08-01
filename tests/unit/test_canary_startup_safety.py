"""Regression tests for zero-write API canary startup."""

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.api.main as api_main
from src.core.admin_ops.application.api_key_service import ApiKeyService


@pytest.mark.asyncio
async def test_canary_skips_api_key_bootstrap(monkeypatch):
    monkeypatch.setenv("AMBER_CANARY", "true")

    with patch(
        "src.core.admin_ops.application.api_key_service.ApiKeyService"
    ) as api_key_service:
        bootstrapped = await api_main._bootstrap_api_key_if_allowed(
            session=object(), dev_key="must-not-be-used"
        )

    assert bootstrapped is False
    api_key_service.assert_not_called()


def test_lifespan_routes_api_key_bootstrap_through_the_canary_guard():
    lifespan_source = inspect.getsource(api_main.lifespan)

    assert "await _bootstrap_api_key_if_allowed(session, dev_key)" in lifespan_source
    assert "service.ensure_bootstrap_key" not in lifespan_source


@pytest.mark.asyncio
async def test_normal_startup_bootstraps_the_configured_key_once(monkeypatch):
    monkeypatch.delenv("AMBER_CANARY", raising=False)

    with patch(
        "src.core.admin_ops.application.api_key_service.ApiKeyService"
    ) as api_key_service:
        api_key_service.return_value.ensure_bootstrap_key = AsyncMock()
        bootstrapped = await api_main._bootstrap_api_key_if_allowed(
            session=object(), dev_key="configured-key"
        )

    assert bootstrapped is True
    api_key_service.assert_called_once()
    api_key_service.return_value.ensure_bootstrap_key.assert_awaited_once_with(
        "configured-key", name="Development Key"
    )


@pytest.mark.asyncio
async def test_canary_authentication_does_not_update_last_used_at(monkeypatch):
    monkeypatch.setenv("AMBER_CANARY", "true")
    original_last_used_at = datetime(2026, 7, 31, tzinfo=UTC)
    key_record = SimpleNamespace(last_used_at=original_last_used_at)
    result = MagicMock()
    result.scalars.return_value.first.return_value = key_record
    session = SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock())

    validated = await ApiKeyService(session).validate_key("existing-key")

    assert validated is key_record
    assert key_record.last_used_at == original_last_used_at
    session.commit.assert_not_awaited()
