from types import SimpleNamespace

import pytest

from src.core.retrieval.application.retrieval_service import RetrievalService
from src.core.retrieval.application.retrieval_service import VectorSearchTarget
from src.core.retrieval.domain.ports.vector_store_port import SearchResult


@pytest.mark.asyncio
async def test_generated_results_are_kept_only_when_repository_exposes_same_generation():
    service = object.__new__(RetrievalService)
    service.document_repository = SimpleNamespace(
        get_chunks=lambda _ids: _async_result(
            [
                SimpleNamespace(id="current", generation_id="gen-current"),
                SimpleNamespace(id="legacy", generation_id=None),
            ]
        )
    )

    results = [
        SearchResult("current", "doc-1", "tenant-1", 0.9, generation_id="gen-current"),
        SearchResult("stale", "doc-1", "tenant-1", 0.8, generation_id="gen-stale"),
        SearchResult("legacy", "doc-2", "tenant-1", 0.7),
        SearchResult("legacy-stale", "doc-1", "tenant-1", 0.6),
    ]

    validated = await service._filter_unpublished_generation_results(results)

    assert [result.chunk_id for result in validated] == ["current", "legacy"]


@pytest.mark.asyncio
async def test_vector_search_overfetches_before_generation_filtering():
    seen_limits = []

    async def search(**kwargs):
        seen_limits.append(kwargs["limit"])
        return [
            SearchResult("stale", "doc-1", "tenant-1", 0.9, generation_id="old"),
            SearchResult("current", "doc-1", "tenant-1", 0.8, generation_id="current"),
        ]

    service = object.__new__(RetrievalService)
    service.vector_searcher = SimpleNamespace(search=search)
    service.config = SimpleNamespace(score_threshold=0.0)
    service.document_repository = SimpleNamespace(
        get_chunks=lambda _ids: _async_result(
            [SimpleNamespace(id="current", generation_id="current")]
        )
    )

    results, _trace = await service._search_vector_targets(
        query_vector=[0.1],
        vector_targets=[VectorSearchTarget("tenant-1", "amber_default")],
        limit=1,
        filters={},
    )

    assert seen_limits == [3]
    assert [result.chunk_id for result in results] == ["current"]


async def _async_result(value):
    return value
