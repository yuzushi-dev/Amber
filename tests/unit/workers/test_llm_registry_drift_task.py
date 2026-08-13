"""
Unit tests for issue #107: the periodic `check_llm_registry_drift` Celery
beat task.

Write-time validation (`validate_llm_step_override`, applied on the tenant
config PUT endpoint) already rejects a bad provider/model pair at the moment
it is saved. It cannot catch drift introduced *afterwards* -- e.g. a model
that was valid when saved gets retired upstream (the reference incident: a
tenant's `ingestion.chunk_context` pinned to `gemma3:12b`, retired from
Ollama, degraded silently for 3 weeks because `enrich_chunks()` only logs a
per-chunk warning and continues). This periodic sweep re-checks every active
tenant's stored `llm_steps` against the current registry and logs a
structured error for anything that has drifted, without mutating tenants.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers.tasks import _check_llm_registry_drift_async


class FakeTenant:
    def __init__(self, tenant_id, config):
        self.id = tenant_id
        self.config = config


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalars(self._items)


class FakeSession:
    def __init__(self, tenants):
        self._tenants = tenants

    async def execute(self, _query):
        return FakeResult(self._tenants)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _patch_db(tenants):
    """Patch the DB plumbing used inside _check_llm_registry_drift_async so
    it never touches a real database: create_async_engine, sessionmaker, and
    configure_worker_session are all replaced with in-memory fakes that
    surface `tenants` as the active-tenant query result."""
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    fake_session = FakeSession(tenants)

    def fake_sessionmaker(*_args, **_kwargs):
        return lambda: fake_session

    patchers = [
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=fake_engine),
        patch("sqlalchemy.orm.sessionmaker", side_effect=fake_sessionmaker),
        patch("src.core.database.session.configure_worker_session", new=AsyncMock()),
    ]
    return patchers, fake_engine


@pytest.mark.asyncio
async def test_no_active_tenants_reports_ok():
    patchers, fake_engine = _patch_db([])
    for p in patchers:
        p.start()
    try:
        result = await _check_llm_registry_drift_async()
    finally:
        for p in patchers:
            p.stop()

    assert result == {"status": "ok", "tenants_scanned": 0, "findings": []}
    fake_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_tenant_with_valid_override_reports_ok():
    from src.shared.model_registry import DEFAULT_LLM_MODEL

    tenants = [
        FakeTenant(
            "tenant-1",
            {
                "llm_steps": {
                    "ingestion.chunk_context": {
                        "provider": "openai",
                        "model": DEFAULT_LLM_MODEL["openai"],
                    }
                }
            },
        )
    ]
    patchers, _ = _patch_db(tenants)
    for p in patchers:
        p.start()
    try:
        result = await _check_llm_registry_drift_async()
    finally:
        for p in patchers:
            p.stop()

    assert result["status"] == "ok"
    assert result["tenants_scanned"] == 1
    assert result["findings"] == []


@pytest.mark.asyncio
async def test_tenant_with_retired_model_reports_drift_and_logs_error():
    """Reproduces the issue #107 reference incident: a step pinned to a
    model retired from its provider must show up as a finding, and must be
    logged via logger.error without raising (regression guard for the
    `extra=finding` / reserved "message" key collision bug)."""
    tenants = [
        FakeTenant(
            "tenant-1",
            {
                "llm_steps": {
                    "ingestion.chunk_context": {"provider": "ollama", "model": "gemma3:12b"}
                }
            },
        )
    ]
    patchers, _ = _patch_db(tenants)
    for p in patchers:
        p.start()
    try:
        with patch("src.workers.tasks.logger") as mock_logger:
            result = await _check_llm_registry_drift_async()
    finally:
        for p in patchers:
            p.stop()

    assert result["status"] == "drift_detected"
    assert result["tenants_scanned"] == 1
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["tenant_id"] == "tenant-1"
    assert finding["step_id"] == "ingestion.chunk_context"
    assert finding["severity"] == "error"
    assert "gemma3:12b" in finding["message"]

    # logger.error must be called with the finding, and must not raise --
    # this is the regression guard for passing `extra=finding` directly,
    # which crashes because `finding["message"]` collides with the reserved
    # LogRecord.message attribute.
    mock_logger.error.assert_called_once()
    args, kwargs = mock_logger.error.call_args
    assert "llm_registry_drift" in args[0]
    assert "extra" in kwargs
    assert "message" not in kwargs["extra"] or kwargs["extra"] is not finding


@pytest.mark.asyncio
async def test_multiple_tenants_scanned_and_only_errors_logged():
    tenants = [
        FakeTenant("tenant-ok", {}),
        FakeTenant(
            "tenant-bad",
            {"llm_steps": {"ingestion.chunk_context": {"provider": "ollama", "model": "gemma3:12b"}}},
        ),
    ]
    patchers, _ = _patch_db(tenants)
    for p in patchers:
        p.start()
    try:
        result = await _check_llm_registry_drift_async()
    finally:
        for p in patchers:
            p.stop()

    assert result["tenants_scanned"] == 2
    assert result["status"] == "drift_detected"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["tenant_id"] == "tenant-bad"
