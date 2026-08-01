"""Regression tests for zero-write API canary startup."""

import inspect
from unittest.mock import patch

import pytest

import src.api.main as api_main


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
