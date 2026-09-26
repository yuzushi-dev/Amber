from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.retrieval.application.use_cases_query import QueryUseCase
from src.shared.kernel.models.query import (
    QueryFilters,
    QueryOptions,
    QueryRequest,
    QueryResponse,
    TimingInfo,
)


class _Metrics:
    @asynccontextmanager
    async def track_query(self, *_args):
        yield SimpleNamespace()


def _retrieval_result(chunks):
    return SimpleNamespace(
        chunks=chunks,
        trace=[],
        cache_hit=False,
        search_mode="basic",
        router_latency_ms=0,
        reranking_ms=0,
        latency_ms=1,
    )


@pytest.mark.asyncio
async def test_use_case_forwards_filters_and_returns_effective_generation_model(monkeypatch):
    monkeypatch.setattr(
        "src.core.retrieval.application.query.structured_query.structured_executor.try_execute",
        AsyncMock(return_value=None),
    )
    candidate = {"chunk_id": "c1", "document_id": "d1", "content": "evidence"}
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(return_value=_retrieval_result([candidate]))
    generation = MagicMock()
    generation.generate = AsyncMock(
        return_value=SimpleNamespace(
            answer="grounded",
            model="provider:effective-model",
            provider="provider",
            sources=[],
            follow_up_questions=[],
            trace=[],
            tokens_used=1,
            input_tokens=1,
            output_tokens=0,
            cost_estimate=0,
            chunks_used=0,
        )
    )
    use_case = QueryUseCase(retrieval, generation, _Metrics())
    use_case._schedule_context_logging = MagicMock()
    history = [{"role": "user", "content": "previous question"}]
    request = QueryRequest(
        query="follow up",
        filters=QueryFilters(
            document_ids=[],
            edition="commercial",
            audience="admin",
            source_family="zendesk_kb",
        ),
        options=QueryOptions(model="provider:requested-model"),
    )

    response = await use_case.execute(
        request,
        tenant_id="tenant-a",
        http_request_state=SimpleNamespace(
            query_scopes=SimpleNamespace(enforce_groups=False), api_key_id="key-a"
        ),
        conversation_history=history,
    )

    retrieval_kwargs = retrieval.retrieve.await_args.kwargs
    assert retrieval_kwargs["document_ids"] == []
    assert retrieval_kwargs["filters"] == {
        "edition": "commercial",
        "audience": "admin",
        "source_family": "zendesk_kb",
    }
    assert retrieval_kwargs["history"] == history
    assert response.model == "provider:effective-model"


def test_query_response_model_defaults_to_none():
    response = QueryResponse(
        answer="fallback",
        sources=[],
        timing=TimingInfo(total_ms=1),
    )

    assert response.model is None
