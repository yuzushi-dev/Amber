from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.admin_ops.application.metrics.collector import MetricsCollector
from src.core.retrieval.application.retrieval_service import RetrievalResult
from src.shared.kernel.models.query import QueryOptions, QueryRequest


@pytest.mark.asyncio
async def test_get_query_scopes_reads_request_state():
    from src.api.deps import get_query_scopes
    from src.core.tenants.application.query_scopes import QueryScopes

    request = MagicMock()
    request.state.query_scopes = QueryScopes(
        effective_tenant_id="engineering",
        vector_scopes=["default", "engineering"],
        graph_scopes=["default", "engineering"],
        shared_document_owner_tenants=["default"],
    )

    scopes = get_query_scopes(request)

    assert scopes is request.state.query_scopes


@pytest.mark.asyncio
async def test_query_use_case_passes_query_scopes_to_retrieval():
    from src.core.retrieval.application.use_cases_query import QueryUseCase
    from src.core.tenants.application.query_scopes import QueryScopes

    retrieval_service = AsyncMock()
    retrieval_service.retrieve.return_value = RetrievalResult(
        chunks=[],
        query="How do I configure Carbonio?",
        tenant_id="engineering",
        latency_ms=0,
        trace=[],
    )

    generation_service = AsyncMock()
    metrics = MetricsCollector(enable_persistence=False)

    state = MagicMock()
    state.query_scopes = QueryScopes(
        effective_tenant_id="engineering",
        vector_scopes=["default", "engineering"],
        graph_scopes=["default", "engineering"],
        shared_document_owner_tenants=["default"],
    )

    use_case = QueryUseCase(
        retrieval_service=retrieval_service,
        generation_service=generation_service,
        metrics_collector=metrics,
    )

    request = QueryRequest(
        query="How do I configure Carbonio?",
        options=QueryOptions(),
    )

    with patch(
        "src.core.retrieval.application.query.structured_query.structured_executor.try_execute",
        new=AsyncMock(return_value=None),
    ):
        await use_case.execute(
            request=request,
            tenant_id="engineering",
            http_request_state=state,
            user_id="user-1",
        )

    assert retrieval_service.retrieve.call_args.kwargs["query_scopes"] is state.query_scopes
