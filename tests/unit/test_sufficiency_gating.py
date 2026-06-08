"""
Gating tests for the sufficiency loop inside RetrievalService.retrieve().

Verifies retrieve() invokes _run_sufficiency_loop only for vector-based modes
with populated targets, and skips it for GLOBAL (which iterates on its own) and
when the option is off — without a DB/LLM/Milvus.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.retrieval.application import retrieval_service as rs_mod
from src.core.retrieval.application.retrieval_service import (
    RetrievalConfig,
    RetrievalResult,
    RetrievalService,
    VectorSearchTarget,
)
from src.core.tenants.application.query_scopes import QueryScopes
from src.shared.kernel.models.query import QueryOptions, SearchMode


def _scopes() -> QueryScopes:
    return QueryScopes(
        effective_tenant_id="t",
        vector_scopes=["t"],
        graph_scopes=["t"],
        shared_document_owner_tenants=[],
    )


def _service_for_mode(mode: SearchMode) -> RetrievalService:
    svc = RetrievalService.__new__(RetrievalService)
    svc.config = RetrievalConfig()
    svc.circuit_breaker = MagicMock()
    svc._get_effective_tenant_config = AsyncMock(return_value={})
    svc.router = MagicMock()
    svc.router.route = AsyncMock(return_value=mode)
    # No history/rules/memory -> rewriter not invoked, but stub defensively.
    svc.rewriter = MagicMock()
    svc.rewriter.rewrite = AsyncMock(side_effect=lambda q, **_kw: q)
    # Repo without taxonomy method -> taxonomy routing skipped.
    svc.document_repository = object()

    svc._resolve_vector_targets = AsyncMock(
        return_value=[VectorSearchTarget(tenant_id="t", collection_name="c")]
    )
    svc._resolve_graph_targets = AsyncMock(return_value=[])
    svc._execute_vector_search = AsyncMock(
        return_value=RetrievalResult(
            chunks=[{"chunk_id": "a", "score": 0.9, "content": "x"}],
            query="q",
            tenant_id="t",
            latency_ms=0.0,
        )
    )
    svc._execute_global_search = AsyncMock(
        return_value=RetrievalResult(chunks=[], query="q", tenant_id="t", latency_ms=0.0)
    )
    svc._run_sufficiency_loop = AsyncMock()
    return svc


async def _retrieve(svc: RetrievalService, options: QueryOptions) -> RetrievalResult:
    # product context resolver is a pure function; force "unknown" so taxonomy
    # routing contributes no signal regardless of the query text.
    ctx = MagicMock(edition="unknown", audience="unknown", confidence=0.0)
    with patch.object(rs_mod, "resolve_product_context", return_value=ctx):
        return await svc.retrieve(
            query="a plain factual question",
            tenant_id="t",
            options=options,
            query_scopes=_scopes(),
        )


@pytest.mark.asyncio
async def test_loop_invoked_for_basic_mode_when_enabled():
    svc = _service_for_mode(SearchMode.BASIC)
    await _retrieve(svc, QueryOptions(use_sufficiency_loop=True, search_mode=SearchMode.BASIC))
    svc._run_sufficiency_loop.assert_awaited_once()


@pytest.mark.asyncio
async def test_loop_skipped_when_option_off():
    svc = _service_for_mode(SearchMode.BASIC)
    await _retrieve(svc, QueryOptions(use_sufficiency_loop=False, search_mode=SearchMode.BASIC))
    svc._run_sufficiency_loop.assert_not_awaited()


@pytest.mark.asyncio
async def test_loop_skipped_when_max_rounds_zero():
    svc = _service_for_mode(SearchMode.BASIC)
    await _retrieve(
        svc,
        QueryOptions(
            use_sufficiency_loop=True, max_sufficiency_rounds=0, search_mode=SearchMode.BASIC
        ),
    )
    svc._run_sufficiency_loop.assert_not_awaited()


@pytest.mark.asyncio
async def test_loop_skipped_for_global_mode():
    svc = _service_for_mode(SearchMode.GLOBAL)
    await _retrieve(svc, QueryOptions(use_sufficiency_loop=True, search_mode=SearchMode.GLOBAL))
    # GLOBAL populates graph_targets, leaves vector_targets empty -> loop skipped.
    svc._run_sufficiency_loop.assert_not_awaited()
    svc._execute_global_search.assert_awaited_once()
