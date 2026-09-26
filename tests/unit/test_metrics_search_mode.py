"""
Tests for PR-04: Search mode and router latency in query metrics.
"""

import json

import pytest


class _Redis:
    def __init__(self):
        self.values = {}
        self.lists = {}

    async def setex(self, key, _ttl, value):
        self.values[key] = value

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, *_args):
        return None

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : end + 1]

    async def mget(self, keys):
        return [self.values.get(key) for key in keys]


@pytest.mark.asyncio
async def test_search_mode_survives_redis_round_trip_and_legacy_defaults_unknown():
    from src.core.admin_ops.application.metrics.collector import MetricsCollector, QueryMetrics

    collector = MetricsCollector(redis_url="fake://redis")
    redis = _Redis()
    collector._client = redis
    metrics = QueryMetrics(
        query_id="q-1", tenant_id="tenant-1", query="question", search_mode="basic"
    )

    await collector.record(metrics)
    recent = await collector.get_recent(tenant_id="tenant-1")

    assert json.loads(redis.values["metrics:query:q-1"])["search_mode"] == "basic"
    assert recent[0].search_mode == "basic"

    failed = QueryMetrics(
        query_id="q-error", tenant_id="tenant-1", query="failed route", success=False,
        search_mode="unknown",
    )
    await collector.record(failed)
    failed_recent = await collector.get_recent(tenant_id="tenant-1")
    assert failed_recent[0].success is False
    assert failed_recent[0].search_mode == "unknown"

    legacy_record = metrics.to_dict()
    legacy_record.update(query_id="q-legacy", query="old")
    legacy_record.pop("search_mode")
    redis.values["metrics:query:q-legacy"] = json.dumps(legacy_record)
    redis.lists["metrics:queries:tenant-1"].append("q-legacy")
    legacy = await collector.get_recent(tenant_id="tenant-1")
    assert legacy[2].search_mode == "unknown"


class TestMetricsSearchModeFields:
    """Test that QueryMetrics includes search_mode and router_latency_ms."""

    def test_query_metrics_has_search_mode_field(self):
        """Test that QueryMetrics dataclass has search_mode field."""
        from src.core.admin_ops.application.metrics.collector import QueryMetrics

        metrics = QueryMetrics(
            query_id="test-123",
            tenant_id="tenant-1",
            query="test query",
        )

        # Should have search_mode attribute
        assert hasattr(metrics, 'search_mode'), "QueryMetrics should have search_mode field"
        assert metrics.search_mode == "unknown"  # default value

    def test_query_metrics_has_router_latency_field(self):
        """Test that QueryMetrics dataclass has router_latency_ms field."""
        from src.core.admin_ops.application.metrics.collector import QueryMetrics

        metrics = QueryMetrics(
            query_id="test-123",
            tenant_id="tenant-1",
            query="test query",
        )

        # Should have router_latency_ms attribute
        assert hasattr(metrics, 'router_latency_ms'), "QueryMetrics should have router_latency_ms field"
        assert metrics.router_latency_ms == 0.0  # default value

    def test_query_metrics_to_dict_includes_new_fields(self):
        """Test that to_dict() includes search_mode and router_latency_ms."""
        from src.core.admin_ops.application.metrics.collector import QueryMetrics

        metrics = QueryMetrics(
            query_id="test-123",
            tenant_id="tenant-1",
            query="test query",
            search_mode="GLOBAL",
            router_latency_ms=12.5,
        )

        d = metrics.to_dict()

        assert "search_mode" in d, "to_dict() should include search_mode"
        assert "router_latency_ms" in d, "to_dict() should include router_latency_ms"
        assert d["search_mode"] == "GLOBAL"
        assert d["router_latency_ms"] == 12.5


class TestRetrievalResultSearchMode:
    """Test that RetrievalResult includes search_mode."""

    def test_retrieval_result_has_search_mode_field(self):
        """Test that RetrievalResult dataclass has search_mode field."""
        from src.core.retrieval.application.retrieval_service import RetrievalResult

        result = RetrievalResult(
            chunks=[],
            query="test",
            tenant_id="tenant-1",
            latency_ms=100.0,
        )

        # Should have search_mode attribute
        assert hasattr(result, 'search_mode'), "RetrievalResult should have search_mode field"

    def test_retrieval_result_has_router_latency_field(self):
        """Test that RetrievalResult includes router_latency_ms."""
        from src.core.retrieval.application.retrieval_service import RetrievalResult

        result = RetrievalResult(
            chunks=[],
            query="test",
            tenant_id="tenant-1",
            latency_ms=100.0,
        )

        assert hasattr(result, 'router_latency_ms'), "RetrievalResult should have router_latency_ms field"
