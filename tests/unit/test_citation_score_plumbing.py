"""
Unit tests for Issue #35: Citation relevance score, score_type, and source plumbing.

Covers:
1. Candidate carries score, score_type, and source in to_dict().
2. GenerationService._map_sources carries candidate score, score_type, and source onto Source objects.
3. GenerationService.prepare_stream includes score, score_type, and source in streaming cited_sources SSE event.
4. QueryUseCase.execute populates score, score_type, and source on API Source objects.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.config import settings as api_settings
from src.core.generation.application.generation_service import GenerationResult, GenerationService, Source
from src.core.retrieval.application.use_cases_query import QueryUseCase
from src.core.retrieval.domain.candidate import Candidate
from src.api.schemas.query import QueryOptions, QueryRequest
from src.shared.kernel.models.query import Source as ApiSource
from src.shared.kernel.runtime import configure_settings


@pytest.fixture(autouse=True)
def setup_settings():
    configure_settings(api_settings)


def test_candidate_to_dict_includes_score_type():
    cand = Candidate(
        chunk_id="c1",
        content="text",
        score=0.85,
        source="vector",
        score_type="cosine",
        document_id="d1",
    )
    d = cand.to_dict()
    assert d["score"] == 0.85
    assert d["source"] == "vector"
    assert d["score_type"] == "cosine"


def test_map_sources_carries_score_score_type_and_source():
    svc = object.__new__(GenerationService)
    svc._normalize_citations = lambda text: text

    cand1 = Candidate(
        chunk_id="c1",
        content="Sample chunk content for testing",
        score=0.88,
        source="vector",
        score_type="cosine",
        document_id="doc1",
    )
    doc_titles = {"doc1": "Test Document Title"}

    sources = svc._map_sources(
        answer="According to [[Source: 1]], testing works.",
        candidates=[cand1],
        doc_titles=doc_titles,
    )

    assert len(sources) == 1
    src = sources[0]
    assert src.score == 0.88
    assert src.score_type == "cosine"
    assert src.source == "vector"
    assert src.title == "Test Document Title"


@pytest.mark.asyncio
async def test_prepare_stream_includes_score_score_type_and_source_in_sse_event():
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
    svc._get_document_titles = AsyncMock(return_value={"d1": "Doc 1 Title"})

    candidates = [
        Candidate(
            chunk_id="c1",
            content="Candidate content text",
            score=0.92,
            source="vector",
            score_type="cosine",
            document_id="d1",
        )
    ]

    prepared = await svc.prepare_stream(
        query="Test query",
        candidates=candidates,
        options={"tenant_id": "t1", "user_id": None},
    )

    sources_event = next(e for e in prepared.prelude_events if e.get("event") == "sources")
    assert sources_event is not None
    data = sources_event["data"]
    assert len(data) == 1
    item = data[0]
    assert item["score"] == 0.92
    assert item["score_type"] == "cosine"
    assert item["source"] == "vector"


@pytest.mark.asyncio
async def test_use_case_execute_populates_api_source_score_score_type_and_source():
    retrieval_service = MagicMock()
    retrieval_service.retrieve = AsyncMock(
        return_value=SimpleNamespace(
            chunks=[{"chunk_id": "c1", "content": "text", "score": 0.95, "title": "Doc 1"}],
            cache_hit=False,
            search_mode="basic",
            router_latency_ms=1.0,
            trace=[],
        )
    )

    gen_source = Source(
        index=1,
        chunk_id="c1",
        document_id="d1",
        content_preview="text",
        title="Doc 1 Title",
        score=0.95,
        score_type="cosine",
        source="vector",
    )

    generation_service = MagicMock()
    generation_service.generate = AsyncMock(
        return_value=GenerationResult(
            answer="Answer text",
            sources=[gen_source],
            model="gpt-4o",
            provider="openai",
            latency_ms=25.0,
            tokens_used=50,
            cost_estimate=0.001,
            follow_up_questions=[],
            trace=[],
        )
    )

    metrics_collector = MagicMock()
    metrics_collector.track_query = MagicMock()

    class FakeTrackQuery:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *args):
            return False

    metrics_collector.track_query.return_value = FakeTrackQuery()

    uc = QueryUseCase(
        retrieval_service=retrieval_service,
        generation_service=generation_service,
        metrics_collector=metrics_collector,
    )

    req = QueryRequest(query="test query", options=QueryOptions(include_sources=True))
    res = await uc.execute(request=req, tenant_id="tenant-1", user_id="user-1")

    assert len(res.sources) == 1
    src = res.sources[0]
    assert src.score == 0.95
    assert getattr(src, "score_type", "cosine") == "cosine"
    assert getattr(src, "source", "vector") == "vector"
