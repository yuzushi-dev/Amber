"""
Security tests for Task 5: remove fail-open tenant/user fallbacks.

Verifies that:
- _get_tenant_id raises HTTP 401 when request.state.tenant_id is absent
- chat history ownership raises HTTP 401 when the authenticated API key is absent
- graph_editor.get_current_user_tenant_id raises HTTP 401 when missing
- use_cases_query.execute no longer has a "default_user" sentinel
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

# ── Tenant ID: fail-closed helpers ───────────────────────────────────────────


def _make_request(tenant_id=None):
    """Build a mock FastAPI request, optionally with state.tenant_id."""
    req = MagicMock()
    req.headers = {}
    if tenant_id is not None:
        req.state.tenant_id = tenant_id
    else:
        # state exists but tenant_id attribute does NOT
        del req.state.tenant_id
    return req


def test_query_get_tenant_id_raises_401_when_missing():
    """query.py _get_tenant_id must raise 401 when request.state.tenant_id absent."""
    from src.api.routes.query import _get_tenant_id

    req = MagicMock()
    # Remove tenant_id attribute from state entirely
    del req.state.tenant_id

    with pytest.raises(HTTPException) as exc_info:
        _get_tenant_id(req)
    assert exc_info.value.status_code == 401, (
        f"Expected 401, got {exc_info.value.status_code}. "
        "Missing tenant falls back to settings.tenant_id — cross-tenant data leak risk."
    )


def test_query_get_tenant_id_returns_value_when_present():
    """query.py _get_tenant_id returns the state value when it is set."""
    from src.api.routes.query import _get_tenant_id

    req = MagicMock()
    req.state.tenant_id = "acme-corp"
    result = _get_tenant_id(req)
    assert result == "acme-corp"


def test_documents_get_tenant_id_raises_401_when_missing():
    """documents.py _get_tenant_id must raise 401 when tenant_id absent from state."""
    from src.api.routes.documents import _get_tenant_id

    req = MagicMock()
    del req.state.tenant_id

    with pytest.raises(HTTPException) as exc_info:
        _get_tenant_id(req)
    assert exc_info.value.status_code == 401


def test_graph_editor_get_tenant_id_raises_401_when_missing():
    """graph_editor.py get_current_user_tenant_id must raise 401 when absent."""
    from src.api.routes.graph_editor import get_current_user_tenant_id

    req = MagicMock()
    del req.state.tenant_id

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_tenant_id(req)
    assert exc_info.value.status_code == 401


# ── User ID: fail-closed helpers ─────────────────────────────────────────────


def test_query_get_user_id_raises_401_when_no_identity_available():
    """_get_user_id must raise 401 when neither X-User-ID nor api_key_name is available."""
    from src.api.routes.query import _get_user_id

    req = MagicMock()
    req.headers = {}
    del req.state.api_key_name  # no key name either

    with pytest.raises(HTTPException) as exc_info:
        _get_user_id(req)
    assert exc_info.value.status_code == 401, (
        f"Expected 401, got {exc_info.value.status_code}. "
        "Must reject requests with no resolvable user identity."
    )


def test_query_get_user_id_uses_api_key_name_when_header_absent():
    """_get_user_id falls back to api_key_name when X-User-ID is absent (browser flow)."""
    from src.api.routes.query import _get_user_id

    req = MagicMock()
    req.headers = {}
    req.state.api_key_name = "frontend-key"
    result = _get_user_id(req)
    assert result == "frontend-key"


def test_query_get_user_id_returns_value_when_present():
    """query.py _get_user_id returns the header value when it is set."""
    from src.api.routes.query import _get_user_id

    req = MagicMock()
    req.headers = {"X-User-ID": "user-abc-123"}
    result = _get_user_id(req)
    assert result == "user-abc-123"


def test_chat_get_api_key_id_raises_401_when_missing():
    """chat.py history ownership must require the authenticated API key principal."""
    from src.api.routes.chat import _get_api_key_id

    req = MagicMock()
    del req.state.api_key_id

    with pytest.raises(HTTPException) as exc_info:
        _get_api_key_id(req)
    assert exc_info.value.status_code == 401


# ── use_cases_query: no default_user sentinel ────────────────────────────────


def test_use_cases_query_execute_has_no_default_user():
    """execute() must not default user_id to 'default_user'."""
    import inspect

    from src.core.retrieval.application.use_cases_query import QueryUseCase

    sig = inspect.signature(QueryUseCase.execute)
    user_id_param = sig.parameters.get("user_id")
    assert user_id_param is not None, "user_id param missing from execute()"
    assert user_id_param.default != "default_user", (
        "execute() still defaults user_id to 'default_user'. "
        "All conversations will be stored under a shared identity."
    )
