"""
Unit tests for Issue #28.4: Standardize request-bound readers on request.state.tenant_id.

Covers:
1. connectors.py route handlers read request.state.tenant_id.
2. admin/feedback.py route handlers read request.state.tenant_id.
3. LLM providers (ollama.py, anthropic.py) use explicit tenant_id kwargs for usage tracking.
"""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.config import settings as api_settings
from src.shared.kernel.runtime import configure_settings


@pytest.fixture(autouse=True)
def setup_settings():
    configure_settings(api_settings)


def test_connectors_routes_do_not_use_get_current_tenant_or_default():
    """connectors.py handlers must read request.state.tenant_id, not `get_current_tenant() or 'default'`."""
    import src.api.routes.connectors as module

    source = inspect.getsource(module)
    assert "get_current_tenant() or \"default\"" not in source, (
        "connectors.py still contains get_current_tenant() or 'default'. "
        "Route handlers should read request.state.tenant_id or use _get_tenant_id(request)."
    )


def test_admin_feedback_routes_do_not_use_get_current_tenant_or_default():
    """admin/feedback.py handlers must read request.state.tenant_id, not `get_current_tenant() or 'default'`."""
    import src.api.routes.admin.feedback as module

    source = inspect.getsource(module)
    assert "get_current_tenant() or \"default\"" not in source, (
        "admin/feedback.py still contains get_current_tenant() or 'default'. "
        "Route handlers should read request.state.tenant_id or use _get_tenant_id(request)."
    )


@pytest.mark.asyncio
async def test_ollama_provider_usage_tracking_uses_explicit_tenant_id(monkeypatch):
    """OllamaLLMProvider must pass explicit tenant_id to usage_tracker.record_usage."""
    from src.core.generation.domain.provider_models import ProviderConfig
    from src.core.generation.infrastructure.providers.ollama import OllamaLLMProvider

    tracker = MagicMock()
    tracker.record_usage = AsyncMock()

    provider = OllamaLLMProvider(
        config=ProviderConfig(base_url="http://localhost:11434", usage_tracker=tracker),
        use_capacity_limiter=False,
    )
    provider.default_model = "llama3"

    async def fake_create(**kwargs):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="Answer"), finish_reason="stop")]
        mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return mock_resp

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)

    # Call generate with tenant_id="explicit-tenant" in kwargs
    await provider.generate(prompt="Hello", tenant_id="explicit-tenant")

    tracker.record_usage.assert_called_once()
    assert tracker.record_usage.call_args.kwargs.get("tenant_id") == "explicit-tenant"
