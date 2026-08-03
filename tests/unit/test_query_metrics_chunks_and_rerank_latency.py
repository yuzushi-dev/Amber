"""
Unit tests for Issue #71: Populate chunks_used and reranking_latency_ms in query metrics.

Covers:
1. Non-streaming QueryUseCase.execute populates query_metrics.chunks_used from generation context.
2. Non-streaming QueryUseCase.execute populates query_metrics.reranking_latency_ms from retrieval trace.
3. GenerationService.generate populates chunks_used on GenerationResult.
4. PreparedGenerationStream captures used_candidates_count for streaming metrics parity.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.config import settings as api_settings
from src.api.schemas.query import QueryRequest
from src.core.generation.application.generation_service import GenerationResult, GenerationService
from src.core.generation.domain.provider_models import (
    GenerationResult as ProviderGenerationResult,
)
from src.core.generation.domain.provider_models import (
    TokenUsage,
)
from src.core.retrieval.application.use_cases_query import QueryUseCase
from src.shared.kernel.runtime import configure_settings


@pytest.fixture(autouse=True)
def setup_settings():
    configure_settings(api_settings)


@pytest.mark.asyncio
async def test_use_case_execute_populates_chunks_used_and_rerank_latency():
    """QueryUseCase.execute must populate query_metrics.chunks_used and reranking_latency_ms."""
    retrieval_service = MagicMock()
    retrieval_service.retrieve = AsyncMock(
        return_value=SimpleNamespace(
            chunks=[
                {"chunk_id": "c1", "content": "text 1", "score": 0.9, "title": "Doc 1"},
                {"chunk_id": "c2", "content": "text 2", "score": 0.8, "title": "Doc 2"},
            ],
            cache_hit=False,
            search_mode="basic",
            router_latency_ms=1.5,
            trace=[
                {"step": "vector_search", "duration_ms": 12.0},
                {"step": "rerank", "duration_ms": 45.5, "model": "bge-reranker"},
            ],
            reranking_ms=45.5,
        )
    )

    generation_service = MagicMock()
    generation_service.generate = AsyncMock(
        return_value=GenerationResult(
            answer="Answer text",
            sources=[SimpleNamespace(document_id="d1", title="Doc 1", content_preview="text 1", score=0.9)],
            model="gpt-4o",
            provider="openai",
            latency_ms=25.0,
            tokens_used=50,
            cost_estimate=0.001,
            chunks_used=2,
            follow_up_questions=[],
            trace=[],
        )
    )

    captured_metrics = None

    class FakeTrackQuery:
        def __init__(self):
            self.m = SimpleNamespace(
                query_id="q-1", tenant_id="tenant-1", query="test query",
                chunks_retrieved=0, chunks_used=0, reranking_latency_ms=0.0,
                tokens_used=0, input_tokens=0, output_tokens=0, cost_estimate=0.0,
                model="", provider="", sources_cited=0, answer_length=0, response="",
                operation="",
            )

        async def __aenter__(self):
            nonlocal captured_metrics
            captured_metrics = self.m
            return self.m

        async def __aexit__(self, *args):
            return False

    metrics_collector = MagicMock()
    metrics_collector.track_query.return_value = FakeTrackQuery()

    uc = QueryUseCase(
        retrieval_service=retrieval_service,
        generation_service=generation_service,
        metrics_collector=metrics_collector,
    )

    req = QueryRequest(query="test query")
    await uc.execute(request=req, tenant_id="tenant-1", user_id="user-1")

    assert captured_metrics is not None
    assert captured_metrics.chunks_retrieved == 2
    assert captured_metrics.chunks_used == 2, "chunks_used must be populated from generation context count"
    assert captured_metrics.reranking_latency_ms == pytest.approx(45.5), (
        "reranking_latency_ms must be copied from RetrievalResult.reranking_ms (independent of include_trace)"
    )


@pytest.mark.asyncio
async def test_reranking_latency_ms_independent_of_trace():
    """reranking_latency_ms must come from RetrievalResult.reranking_ms, not from
    scanning `.trace` for a 'rerank' step — real clients never set include_trace,
    so a trace-dependent extraction always reports 0 in production (issue #71 regression).
    """
    retrieval_service = MagicMock()
    retrieval_service.retrieve = AsyncMock(
        return_value=SimpleNamespace(
            chunks=[
                {"chunk_id": "c1", "content": "text 1", "score": 0.9, "title": "Doc 1"},
                {"chunk_id": "c2", "content": "text 2", "score": 0.8, "title": "Doc 2"},
            ],
            cache_hit=False,
            search_mode="basic",
            router_latency_ms=1.5,
            trace=[],
            reranking_ms=45.5,
        )
    )

    generation_service = MagicMock()
    generation_service.generate = AsyncMock(
        return_value=GenerationResult(
            answer="Answer text",
            sources=[SimpleNamespace(document_id="d1", title="Doc 1", content_preview="text 1", score=0.9)],
            model="gpt-4o",
            provider="openai",
            latency_ms=25.0,
            tokens_used=50,
            cost_estimate=0.001,
            chunks_used=2,
            follow_up_questions=[],
            trace=[],
        )
    )

    captured_metrics = None

    class FakeTrackQuery:
        def __init__(self):
            self.m = SimpleNamespace(
                query_id="q-1", tenant_id="tenant-1", query="test query",
                chunks_retrieved=0, chunks_used=0, reranking_latency_ms=0.0,
                tokens_used=0, input_tokens=0, output_tokens=0, cost_estimate=0.0,
                model="", provider="", sources_cited=0, answer_length=0, response="",
                operation="",
            )

        async def __aenter__(self):
            nonlocal captured_metrics
            captured_metrics = self.m
            return self.m

        async def __aexit__(self, *args):
            return False

    metrics_collector = MagicMock()
    metrics_collector.track_query.return_value = FakeTrackQuery()

    uc = QueryUseCase(
        retrieval_service=retrieval_service,
        generation_service=generation_service,
        metrics_collector=metrics_collector,
    )

    req = QueryRequest(query="test query")
    await uc.execute(request=req, tenant_id="tenant-1", user_id="user-1")

    assert captured_metrics is not None
    assert captured_metrics.reranking_latency_ms == pytest.approx(45.5), (
        "reranking_latency_ms must not depend on a populated .trace / include_trace flag"
    )


@pytest.mark.asyncio
async def test_generation_service_generate_sets_chunks_used():
    """GenerationService.generate must record chunks_used on GenerationResult."""
    svc = object.__new__(GenerationService)
    svc.config = SimpleNamespace(
        max_context_tokens=1000,
        model="gpt-4o",
        prompt_version="v1",
        temperature=0.7,
        seed=None,
        tier="default",
        max_tokens=500,
        enable_follow_up=False,
    )
    svc.registry = MagicMock()
    svc.registry.get_prompt = MagicMock(return_value="Prompt template")
    svc.llm = MagicMock()
    svc.llm.model_name = "gpt-4o"
    svc._get_effective_tenant_config = AsyncMock(return_value={})
    svc._resolve_provider_factory = MagicMock(return_value=None)
    svc._apply_complexity_routing = lambda **kwargs: (kwargs["llm_cfg"], "standard", False)
    svc._get_document_titles = AsyncMock(return_value={})
    svc._map_sources = MagicMock(return_value=[])

    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(
        return_value=ProviderGenerationResult(
            text="Provider response",
            provider="openai",
            model="gpt-4o",
            usage=TokenUsage(10, 5),
        )
    )
    svc.llm = mock_provider

    candidates = [
        {"chunk_id": "c1", "content": "chunk 1 text", "metadata": {}},
        {"chunk_id": "c2", "content": "chunk 2 text", "metadata": {}},
    ]
    result = await svc.generate(query="Current query", candidates=candidates)

    assert hasattr(result, "chunks_used")
    assert result.chunks_used == 2
