"""
Unit tests for Issue #28.1 & #28.2: Fail-closed retrieval scopes & worker scope.

#28.1: When query_scopes is omitted (None) by a caller to RetrievalService.retrieve(),
retrieval_service must derive group enforcement from tenant config fail-closed,
rather than defaulting to enforce_groups=False.

#28.2: The worker benchmark evaluation task in workers/tasks.py must explicitly
pass a privileged query_scopes (enforce_groups=False) so benchmark evaluation
is not blocked when a tenant has groups_enforced=True.
"""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.config import settings as api_settings
from src.core.retrieval.application.retrieval_service import RetrievalResult, RetrievalService
from src.core.tenants.application.query_scopes import QueryScopes, resolve_query_scopes
from src.shared.kernel.models.query import SearchMode
from src.shared.kernel.runtime import configure_settings


@pytest.fixture(autouse=True)
def setup_settings():
    configure_settings(api_settings)


def _make_mock_doc_repo():
    repo = MagicMock()
    repo.list_visible_document_ids_by_taxonomy = AsyncMock(return_value=None)
    return repo


@pytest.mark.asyncio
async def test_retrieve_omitted_query_scopes_derives_fail_closed_from_tenant_config():
    """When query_scopes=None, retrieve() must derive enforce_groups from tenant_config.

    If tenant_config has groups_enforced=True, resolved_scopes must have enforce_groups=True.
    """
    svc = object.__new__(RetrievalService)
    svc.config = MagicMock(top_k=5)
    svc.tuning = MagicMock()
    svc.tuning.get_effective_tenant_config = AsyncMock(
        return_value={"groups_enforced": True}
    )
    svc.document_repository = _make_mock_doc_repo()
    svc.router = MagicMock(route=AsyncMock(return_value=SearchMode.BASIC))
    svc.rewriter = MagicMock()
    svc.circuit_breaker = MagicMock()

    captured_scopes = []

    async def fake_search_targets(viewer_tenant_id, query_scopes, *args, **kwargs):
        captured_scopes.append(query_scopes)
        return [], []

    async def fake_execute_vector_search(*args, **kwargs):
        return RetrievalResult(chunks=[], cache_hit=False, query="q", tenant_id="t", latency_ms=1.0)

    svc._resolve_vector_targets = fake_search_targets
    svc._resolve_graph_targets = fake_search_targets
    svc._execute_vector_search = fake_execute_vector_search

    # Call retrieve() with query_scopes=None on a tenant with groups_enforced=True
    await svc.retrieve("test query", tenant_id="tenant-enforced", query_scopes=None)

    assert len(captured_scopes) > 0, "Retrieval should have resolved query targets"
    for scope in captured_scopes:
        assert scope is not None
        assert scope.enforce_groups is True, (
            "When query_scopes is omitted, enforce_groups must be derived "
            "from tenant_config (groups_enforced=True -> fail closed)."
        )


@pytest.mark.asyncio
async def test_retrieve_explicit_query_scopes_overrides_tenant_config():
    """When an explicit query_scopes is passed, retrieve() must respect it."""
    svc = object.__new__(RetrievalService)
    svc.config = MagicMock(top_k=5)
    svc.tuning = MagicMock()
    svc.tuning.get_effective_tenant_config = AsyncMock(
        return_value={"groups_enforced": True}
    )
    svc.document_repository = _make_mock_doc_repo()
    svc.router = MagicMock(route=AsyncMock(return_value=SearchMode.BASIC))
    svc.rewriter = MagicMock()
    svc.circuit_breaker = MagicMock()

    captured_scopes = []

    async def fake_search_targets(viewer_tenant_id, query_scopes, *args, **kwargs):
        captured_scopes.append(query_scopes)
        return [], []

    async def fake_execute_vector_search(*args, **kwargs):
        return RetrievalResult(chunks=[], cache_hit=False, query="q", tenant_id="t", latency_ms=1.0)

    svc._resolve_vector_targets = fake_search_targets
    svc._resolve_graph_targets = fake_search_targets
    svc._execute_vector_search = fake_execute_vector_search

    explicit_scope = resolve_query_scopes("tenant-enforced", enforce_groups=False)
    await svc.retrieve("test query", tenant_id="tenant-enforced", query_scopes=explicit_scope)

    assert len(captured_scopes) > 0
    for scope in captured_scopes:
        assert scope.enforce_groups is False, "Explicit query_scopes must not be overridden"


def test_worker_tasks_benchmark_passes_explicit_query_scopes():
    """#28.2: workers/tasks.py benchmark retrieval must pass explicit query_scopes."""
    import src.workers.tasks as tasks_module

    source = inspect.getsource(tasks_module)

    # Check that retrieve() call in benchmark execution passes worker_scopes
    assert "worker_scopes = resolve_query_scopes" in source or "query_scopes=worker_scopes" in source or "query_scopes=resolve_query_scopes" in source, (
        "workers/tasks.py must pass query_scopes to retrieval_service.retrieve() "
        "so benchmark evaluation is not fail-closed when a tenant has groups_enforced=True."
    )
