"""
Tests for PR-01: Result cache restoration.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


class TestResultCacheEnabled:
    """Test that result cache is enabled and working."""

    def test_retrieval_service_has_result_cache(self):
        """Test that RetrievalService has result_cache attribute."""
        # Check that result_cache is accessed in the code
        with open(Path(__file__).resolve().parents[2] / 'src/core/retrieval/application/retrieval_service.py') as f:
            content = f.read()

        assert 'result_cache' in content, "RetrievalService should use result_cache"
        assert 'self.result_cache.get' in content, "Should call result_cache.get"

    def test_cache_bypass_removed(self):
        """Test that FORCE MISS bypass is removed."""
        with open(Path(__file__).resolve().parents[2] / 'src/core/retrieval/application/retrieval_service.py') as f:
            content = f.read()

        # The bypass should NOT be present
        assert 'cached_result = None  # FORCE MISS' not in content, \
            "FORCE MISS bypass should be removed"
        assert '# FORCE MISS' not in content, \
            "FORCE MISS comment should be removed"

    def test_cache_hit_check_active(self):
        """Test that cache hit check is active (not commented out)."""
        with open(Path(__file__).resolve().parents[2] / 'src/core/retrieval/application/retrieval_service.py') as f:
            content = f.read()

        # Check that there's code checking cached_result
        # The pattern should be: if cached_result: ... continue
        assert 'if cached_result:' in content, \
            "Should have active cache hit check"


class TestResultCacheClass:
    """Test ResultCache class functionality."""

    def test_result_cache_import(self):
        """Test that ResultCache can be imported."""
        from src.core.cache.result_cache import ResultCache, ResultCacheConfig
        assert ResultCache is not None
        assert ResultCacheConfig is not None

    def test_result_cache_config_defaults(self):
        """Test ResultCacheConfig default values."""
        from src.core.cache.result_cache import ResultCacheConfig

        config = ResultCacheConfig()
        assert config.ttl_seconds == 3600
        assert config.enabled is True
        assert config.key_prefix == "result_cache"

    @pytest.mark.asyncio
    async def test_result_cache_get_returns_none_when_empty(self):
        """Test that get returns None for missing cache entries."""
        from src.core.cache.result_cache import ResultCache, ResultCacheConfig

        # Mock Redis
        config = ResultCacheConfig()
        cache = ResultCache(config)
        cache._client = AsyncMock()
        cache._client.get = AsyncMock(return_value=None)

        result = await cache.get("query", "tenant", {})
        assert result is None


class _MemoryRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def setex(self, key, ttl, value):
        self.values[key] = value


@pytest.mark.asyncio
async def test_cache_roundtrips_score_provenance_without_changing_order():
    from src.core.cache.result_cache import ResultCache

    cache = ResultCache()
    cache._client = _MemoryRedis()
    ids = ["chunk-rerank", "chunk-rrf", "chunk-cosine"]
    scores = [0.2, 0.03, 0.9]
    score_types = ["reranker", "rrf", "cosine"]
    sources = ["vector", "hybrid", "vector"]

    assert await cache.set(
        "query", "tenant", ids, scores, score_types=score_types, sources=sources
    )
    result = await cache.get("query", "tenant")

    assert result is not None
    assert result.chunk_ids == ids
    assert result.scores == scores
    assert result.score_types == score_types
    assert result.sources == sources


@pytest.mark.asyncio
async def test_cache_old_entry_metadata_is_unknown():
    from src.core.cache.result_cache import ResultCache

    cache = ResultCache()
    cache._client = _MemoryRedis()
    ids = ["chunk-a", "chunk-b"]
    key = cache._make_key("tenant", cache._hash_request("query", "tenant"))
    cache._client.values[key] = json.dumps(
        {"chunk_ids": ids, "scores": [0.7, 0.6], "cached_at": "2099", "query_hash": "old"}
    )

    result = await cache.get("query", "tenant")

    assert result is not None
    assert result.score_types == ["unknown", "unknown"]
    assert result.sources == ["unknown", "unknown"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score_types", "sources", "expected_score_types", "expected_sources"),
    [
        ("reranker", ["vector", "hybrid"], ["unknown", "unknown"], ["vector", "hybrid"]),
        (["reranker"], ["vector", "hybrid"], ["unknown", "unknown"], ["vector", "hybrid"]),
        (["reranker", 7], ["vector", None], ["unknown", "unknown"], ["unknown", "unknown"]),
    ],
)
async def test_cache_malformed_provenance_becomes_unknown(
    score_types, sources, expected_score_types, expected_sources
):
    from src.core.cache.result_cache import ResultCache

    cache = ResultCache()
    cache._client = _MemoryRedis()
    ids = ["chunk-a", "chunk-b"]
    key = cache._make_key("tenant", cache._hash_request("query", "tenant"))
    cache._client.values[key] = json.dumps(
        {
            "chunk_ids": ids,
            "scores": [0.7, 0.6],
            "score_types": score_types,
            "sources": sources,
            "cached_at": "2099",
        }
    )

    result = await cache.get("query", "tenant")

    assert result is not None
    assert result.chunk_ids == ids
    assert result.score_types == expected_score_types
    assert result.sources == expected_sources
