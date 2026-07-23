"""Regression test for the RLS tenant-GUC source in get_db_session.

get_db_session must set app.current_tenant from request.state.tenant_id
(populated deterministically by AuthenticationMiddleware), NOT from the
get_current_tenant() contextvar — the contextvar is set inside the auth
BaseHTTPMiddleware and does not reliably propagate to endpoint dependencies,
which left the GUC empty on pooled connections and made FORCE-RLS reads (e.g.
document title lookups) return 0 rows intermittently ("Untitled").
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import src.api.deps as deps


def _drive_get_db_session(request, monkeypatch):
    """Run the get_db_session dependency far enough to capture its set_config
    calls, with a fully mocked async session."""
    calls = []

    session = MagicMock()

    async def _execute(stmt, params=None):
        calls.append(params or {})
        return MagicMock()

    session.execute = _execute
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(deps, "_get_async_session_maker", lambda: (lambda: _Ctx()))
    # Contextvar returns a DIFFERENT tenant, to prove request.state wins.
    monkeypatch.setattr(
        "src.shared.context.get_current_tenant", lambda: "ctxvar-wrong-tenant"
    )

    async def _run():
        gen = deps.get_db_session(request)
        await gen.__anext__()  # runs up to `yield session` (all set_config calls)
        await gen.aclose()

    asyncio.run(_run())
    return calls


def test_tenant_guc_sourced_from_request_state(monkeypatch):
    request = SimpleNamespace(
        state=SimpleNamespace(
            tenant_id="acme", permissions=[], group_ids=[], groups_enforced=False,
            tenant_role="user",
        )
    )
    calls = _drive_get_db_session(request, monkeypatch)
    # The first set_config sets app.current_tenant; it must use request.state.
    assert calls, "get_db_session made no set_config calls"
    assert calls[0].get("tenant_id") == "acme"
    assert all(c.get("tenant_id") != "ctxvar-wrong-tenant" for c in calls)


def test_tenant_guc_falls_back_to_contextvar_when_state_missing(monkeypatch):
    # No tenant_id on request.state -> fall back to the contextvar (superset,
    # never worse than pre-fix behaviour).
    request = SimpleNamespace(
        state=SimpleNamespace(
            permissions=[], group_ids=[], groups_enforced=False, tenant_role="user",
        )
    )
    calls = _drive_get_db_session(request, monkeypatch)
    assert calls[0].get("tenant_id") == "ctxvar-wrong-tenant"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
