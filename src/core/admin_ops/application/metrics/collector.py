"""
Metrics Collector
=================

Centralized metrics collection for RAG pipeline monitoring and evaluation.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    """Metrics for a single query."""

    query_id: str
    tenant_id: str
    query: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Operation type: rag_query, chat_query, summarization, extraction
    operation: str = "rag_query"
    # Response text (for display)
    response: str = ""

    # Latency breakdown (ms)
    embedding_latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    reranking_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    # Retrieval stats
    chunks_retrieved: int = 0
    chunks_used: int = 0
    cache_hit: bool = False

    # Generation stats
    tokens_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0
    model: str = ""
    provider: str = ""
    success: bool = True
    error_message: str | None = None
    conversation_id: str | None = None

    # Quality signals
    sources_cited: int = 0
    answer_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to flat dictionary for storage (matches frontend interface)."""
        return {
            "query_id": self.query_id,
            "tenant_id": self.tenant_id,
            "query": self.query,
            "timestamp": self.timestamp.isoformat(),
            "operation": self.operation,
            "response": self.response,
            # Latency (flat)
            "embedding_latency_ms": self.embedding_latency_ms,
            "retrieval_latency_ms": self.retrieval_latency_ms,
            "reranking_latency_ms": self.reranking_latency_ms,
            "generation_latency_ms": self.generation_latency_ms,
            "total_latency_ms": self.total_latency_ms,
            # Retrieval (flat)
            "chunks_retrieved": self.chunks_retrieved,
            "chunks_used": self.chunks_used,
            "cache_hit": self.cache_hit,
            # Generation (flat)
            "tokens_used": self.tokens_used,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_estimate": self.cost_estimate,
            "model": self.model,
            "provider": self.provider,
            "success": self.success,
            "error_message": self.error_message,
            "conversation_id": self.conversation_id,
            # Quality (flat)
            "sources_cited": self.sources_cited,
            "answer_length": self.answer_length,
        }


@dataclass
class AggregatedMetrics:
    """Aggregated metrics over a time period."""

    period_start: datetime
    period_end: datetime
    query_count: int = 0

    # Latency percentiles (ms)
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0

    # Cache performance
    cache_hit_rate: float = 0.0

    # Cost tracking
    total_cost: float = 0.0
    avg_cost_per_query: float = 0.0

    # Quality
    avg_sources_per_query: float = 0.0
    avg_answer_length: float = 0.0


class MetricsCollector:
    """
    Centralized metrics collection for the RAG pipeline.

    Supports:
    - Per-query metrics recording
    - Aggregation for dashboards
    - Export to various backends (Redis, Prometheus, etc.)

    Usage:
        collector = MetricsCollector(redis_url="redis://localhost:6379/0")

        async with collector.track_query("q_123", "tenant_1", "What is X?") as metrics:
            # Perform query...
            metrics.chunks_retrieved = 10
            metrics.generation_latency_ms = 500
    """

    def __init__(
        self,
        redis_url: str | None = None,
        enable_persistence: bool = True,
        retention_days: int = 30,
    ):
        self.redis_url = redis_url
        self.enable_persistence = enable_persistence
        self.retention_days = retention_days
        self._client = None

        # In-memory buffer for recent metrics
        self._buffer: list[QueryMetrics] = []
        self._buffer_size = 1000

    async def _get_client(self):
        """Get or create Redis client."""
        if self._client is None and self.redis_url:
            try:
                import redis.asyncio as redis

                self._client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                )
            except ImportError:
                logger.warning("Redis not available for metrics persistence")
        return self._client

    class QueryTracker:
        """Context manager for tracking query metrics."""

        def __init__(self, collector: "MetricsCollector", metrics: QueryMetrics):
            self.collector = collector
            self.metrics = metrics
            self._start_time = None

        async def __aenter__(self) -> QueryMetrics:
            self._start_time = time.perf_counter()
            return self.metrics

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if self._start_time:
                self.metrics.total_latency_ms = (time.perf_counter() - self._start_time) * 1000

            if exc_val:
                self.metrics.success = False
                self.metrics.error_message = str(exc_val)

            await self.collector.record(self.metrics)
            return False

    def track_query(
        self,
        query_id: str,
        tenant_id: str,
        query: str,
    ) -> QueryTracker:
        """Create a context manager for tracking a query."""
        metrics = QueryMetrics(
            query_id=query_id,
            tenant_id=tenant_id,
            query=query,
        )
        return self.QueryTracker(self, metrics)

    async def record(self, metrics: QueryMetrics) -> None:
        """Record completed query metrics."""
        # Add to buffer
        self._buffer.append(metrics)
        if len(self._buffer) > self._buffer_size:
            self._buffer = self._buffer[-self._buffer_size :]

        # Persist to Redis if enabled
        if self.enable_persistence:
            await self._persist(metrics)

        logger.debug(
            f"Recorded metrics for query {metrics.query_id}: "
            f"{metrics.total_latency_ms:.0f}ms, {metrics.tokens_used} tokens"
        )

    async def _persist(self, metrics: QueryMetrics) -> None:
        """Persist metrics to Redis."""
        import json

        client = await self._get_client()
        if not client:
            return

        try:
            key = f"metrics:query:{metrics.query_id}"
            await client.setex(
                key,
                self.retention_days * 86400,
                json.dumps(metrics.to_dict()),
            )

            # Add to time-series list for aggregation
            list_key = f"metrics:queries:{metrics.tenant_id}"
            await client.lpush(list_key, metrics.query_id)
            await client.ltrim(list_key, 0, 9999)  # Keep last 10k query IDs

        except Exception as e:
            logger.warning(f"Failed to persist metrics: {e}")

    async def get_aggregated(
        self,
        tenant_id: str | None = None,
        period_hours: int = 24,
    ) -> AggregatedMetrics:
        """Get aggregated metrics for a time period."""
        from datetime import timedelta

        now = datetime.now(UTC)
        start = now - timedelta(hours=period_hours)

        # Filter buffer for time period
        relevant = [
            m
            for m in self._buffer
            if m.timestamp >= start and (tenant_id is None or m.tenant_id == tenant_id)
        ]

        if not relevant:
            return AggregatedMetrics(period_start=start, period_end=now)

        # Calculate aggregations
        latencies = sorted([m.total_latency_ms for m in relevant])
        costs = [m.cost_estimate for m in relevant]
        cache_hits = sum(1 for m in relevant if m.cache_hit)

        return AggregatedMetrics(
            period_start=start,
            period_end=now,
            query_count=len(relevant),
            p50_latency_ms=latencies[len(latencies) // 2] if latencies else 0,
            p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
            p99_latency_ms=latencies[int(len(latencies) * 0.99)] if latencies else 0,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            cache_hit_rate=cache_hits / len(relevant) if relevant else 0,
            total_cost=sum(costs),
            avg_cost_per_query=sum(costs) / len(relevant) if relevant else 0,
            avg_sources_per_query=sum(m.sources_cited for m in relevant) / len(relevant),
            avg_answer_length=sum(m.answer_length for m in relevant) / len(relevant),
        )

    async def get_recent(
        self,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[QueryMetrics]:
        if not self.enable_persistence:
            # Fallback to buffer if persistence disabled
            relevant = [
                m for m in reversed(self._buffer) if tenant_id is None or m.tenant_id == tenant_id
            ]
            return relevant[:limit]

        # Fetch from Redis
        client = await self._get_client()
        if not client:
            # Fallback if Redis fails
            relevant = [
                m for m in reversed(self._buffer) if tenant_id is None or m.tenant_id == tenant_id
            ]
            return relevant[:limit]

        try:
            # Use tenant-specific list if provided
            list_key = f"metrics:queries:{tenant_id}" if tenant_id else "metrics:queries:default"

            # Fetch most recent query IDs
            query_ids = await client.lrange(list_key, 0, limit - 1)

            if not query_ids:
                return []

            # Fetch details for each query
            metrics_keys = [f"metrics:query:{qid}" for qid in query_ids]
            raw_data = await client.mget(metrics_keys)

            results = []
            import json

            for data in raw_data:
                if data:
                    try:
                        d = json.loads(data)
                        # Reconstruct QueryMetrics from dict
                        # We need to parse nested dicts manually or update constructor
                        # For simplicity, we assume robust parsing or simple reconstruction here
                        # Ideally, QueryMetrics should have a `from_dict` method.

                        m = QueryMetrics(
                            query_id=d["query_id"],
                            tenant_id=d["tenant_id"],
                            query=d["query"],
                            timestamp=datetime.fromisoformat(d["timestamp"]),
                            operation=d.get("operation", "rag_query"),
                            response=d.get("response", ""),
                            embedding_latency_ms=d.get("embedding_latency_ms", 0),
                            retrieval_latency_ms=d.get("retrieval_latency_ms", 0),
                            reranking_latency_ms=d.get("reranking_latency_ms", 0),
                            generation_latency_ms=d.get("generation_latency_ms", 0),
                            total_latency_ms=d.get("total_latency_ms", 0),
                            chunks_retrieved=d.get("chunks_retrieved", 0),
                            chunks_used=d.get("chunks_used", 0),
                            cache_hit=d.get("cache_hit", False),
                            tokens_used=d.get("tokens_used", 0),
                            input_tokens=d.get("input_tokens", 0),
                            output_tokens=d.get("output_tokens", 0),
                            cost_estimate=d.get("cost_estimate", 0.0),
                            model=d.get("model", ""),
                            provider=d.get("provider", ""),
                            success=d.get("success", True),
                            error_message=d.get("error_message"),
                            conversation_id=d.get("conversation_id"),
                            sources_cited=d.get("sources_cited", 0),
                            answer_length=d.get("answer_length", 0),
                        )
                        results.append(m)
                    except Exception as e:
                        logger.warning(f"Failed to parse metric: {e}")
                        continue

            return results

        except Exception as e:
            logger.error(f"Failed to get recent metrics from Redis: {e}")
            # Fallback to buffer
            relevant = [
                m for m in reversed(self._buffer) if tenant_id is None or m.tenant_id == tenant_id
            ]
            return relevant[:limit]

    async def close(self) -> None:
        """Close connections."""
        if self._client:
            await self._client.close()
            self._client = None
