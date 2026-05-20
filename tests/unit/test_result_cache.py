"""
Tests for PR-01: Result cache restoration.
"""
from unittest.mock import AsyncMock

import pytest
from pathlib import Path


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
