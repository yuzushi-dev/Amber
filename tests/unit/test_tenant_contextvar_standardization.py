"""
Unit tests for Issue #28.4: Standardize request-bound readers on request.state.tenant_id.

Covers:
1. connectors.py route handlers read request.state.tenant_id.
2. admin/feedback.py route handlers read request.state.tenant_id.
3. LLM providers (ollama.py, anthropic.py) use explicit tenant_id kwargs for usage tracking.
"""

import inspect
from types import SimpleNamespace
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


@pytest.mark.asyncio
async def test_anthropic_provider_usage_tracking_uses_explicit_tenant_id(monkeypatch):
    """AnthropicLLMProvider must pass explicit tenant_id to usage_tracker.record_usage."""
    from src.core.generation.domain.provider_models import ProviderConfig
    from src.core.generation.infrastructure.providers.anthropic import AnthropicLLMProvider

    tracker = MagicMock()
    tracker.record_usage = AsyncMock()

    provider = AnthropicLLMProvider(
        config=ProviderConfig(api_key="test-key", usage_tracker=tracker),
    )
    provider.default_model = "claude-3-5-sonnet-20241022"

    mock_msg = MagicMock()
    mock_msg.id = "msg-123"
    mock_msg.content = [MagicMock(text="Answer text")]
    mock_msg.usage = MagicMock(input_tokens=12, output_tokens=8)

    async def fake_create(**_kw):
        return mock_msg

    monkeypatch.setattr(provider.client.messages, "create", fake_create)

    await provider.generate(prompt="Hello", tenant_id="explicit-anthropic-tenant")

    tracker.record_usage.assert_called_once()
    assert tracker.record_usage.call_args.kwargs.get("tenant_id") == "explicit-anthropic-tenant"


def test_get_tenant_id_unauthenticated_raises_401():
    """_get_tenant_id must raise 401 if no tenant ID is present in request state or contextvar."""
    from fastapi import HTTPException
    from src.api.routes.connectors import _get_tenant_id

    mock_req = MagicMock()
    mock_req.state = SimpleNamespace()

    with pytest.raises(HTTPException) as exc_info:
        _get_tenant_id(mock_req)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_super_admin_get_pending_feedback_without_tenant_succeeds():
    """Super Admin calling get_pending_feedback without tenant_id in request.state must NOT raise 401."""
    from types import SimpleNamespace
    from src.api.routes.admin.feedback import get_pending_feedback

    mock_request = SimpleNamespace(
        state=SimpleNamespace(is_super_admin=True)  # no tenant_id set
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    res = await get_pending_feedback(request=mock_request, skip=0, limit=10, db=mock_db)
    assert res.data == []
