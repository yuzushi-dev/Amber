"""
Observability Admin Routes
==========================

Endpoints for monitoring system health and business metrics.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from src.amber_platform.composition_root import build_metrics_collector
from src.core.admin_ops.application.metrics.collector import AggregatedMetrics

router = APIRouter(prefix="/observability", tags=["observability"])


class MetricsResponse(BaseModel):
    aggregated: AggregatedMetrics
    recent_queries: list[dict]


@router.get(
    "/metrics/aggregated",
    response_model=AggregatedMetrics,
    summary="Get Aggregated Metrics",
    description="Get system performance metrics aggregated over a time period.",
)
async def get_aggregated_metrics(tenant_id: str | None = None, period_hours: int = 24):
    collector = build_metrics_collector()
    try:
        data = await collector.get_aggregated(tenant_id=tenant_id, period_hours=period_hours)
        return data
    finally:
        await collector.close()


@router.get(
    "/metrics/recent",
    summary="Get Recent Queries",
    description="Get details of recent RAG queries.",
)
async def get_recent_queries(tenant_id: str | None = None, limit: int = 50):
    collector = build_metrics_collector()
    try:
        queries = await collector.get_recent(tenant_id=tenant_id, limit=limit)
        # Convert dataclasses to dicts if needed, or rely on FastAPI encoder
        return [q.to_dict() for q in queries]
    finally:
        await collector.close()


@router.get(
    "/health/deep",
    summary="Deep Health Check",
    description="Check connectivity to all infrastructure components.",
)
async def deep_health_check():
    from src.amber_platform.composition_root import platform

    status_report = {
        "database": "unknown",
        "redis": "unknown",
        "neo4j": "unknown",
        "milvus": "unknown",
    }

    # 1. Check Redis
    try:
        import redis.asyncio as redis

        from src.api.config import settings

        r = redis.from_url(settings.db.redis_url)
        await r.ping()
        await r.close()
        status_report["redis"] = "ok"
    except Exception as e:
        status_report["redis"] = f"error: {str(e)}"

    # 2. Check Neo4j
    try:
        neo = platform.neo4j_client
        await neo.verify_connectivity()
        status_report["neo4j"] = "ok"
    except Exception as e:
        status_report["neo4j"] = f"error: {str(e)}"

    return status_report
