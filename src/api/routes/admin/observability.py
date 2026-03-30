"""
Observability Admin Routes
==========================

Endpoints for monitoring system health and business metrics.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.amber_platform.composition_root import build_metrics_collector
from src.api.config import settings
from src.api.deps import get_db_session, verify_super_admin
from src.core.admin_ops.application.metrics.collector import AggregatedMetrics
from src.core.admin_ops.domain.audit import AuditLog
from src.core.ingestion.domain.document_share import DocumentShare
from src.core.tenants.domain.tenant import Tenant

router = APIRouter(
    prefix="/observability",
    tags=["observability"],
    dependencies=[Depends(verify_super_admin)],
)


class MetricsResponse(BaseModel):
    aggregated: AggregatedMetrics
    recent_queries: list[dict]


class DocumentShareFlagsResponse(BaseModel):
    enable_document_share_management: bool
    enable_upload_time_document_shares: bool
    enable_acl_aware_vector_retrieval: bool
    enable_acl_aware_graph_retrieval: bool


class DocumentShareTenantSummaryResponse(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    share_row_count: int
    shared_document_count: int
    denied_visibility_count: int = 0
    not_found_visibility_count: int = 0


class DocumentShareTotalsResponse(BaseModel):
    share_row_count: int
    shared_document_count: int
    share_add_audit_count: int
    share_replace_audit_count: int
    share_remove_audit_count: int


class DocumentShareQueryMetricsResponse(BaseModel):
    recent_query_count: int
    shared_hits: int
    local_hits: int
    acl_filtered_results: int


class DocumentShareSummaryResponse(BaseModel):
    flags: DocumentShareFlagsResponse
    totals: DocumentShareTotalsResponse
    tenants: list[DocumentShareTenantSummaryResponse]
    query_metrics: DocumentShareQueryMetricsResponse


class DocumentShareAuditEntryResponse(BaseModel):
    id: str
    timestamp: datetime
    actor: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    changes: dict | None = None
    metadata_json: dict | None = None


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
        return [q.to_dict() for q in queries]
    finally:
        await collector.close()


@router.get(
    "/document-shares/summary",
    response_model=DocumentShareSummaryResponse,
    summary="Get Document Share Observability Summary",
    description="Summarize explicit document sharing state, audit counts, and recent shared/local retrieval metrics.",
)
async def get_document_share_summary(
    recent_limit: int = 200,
    session: AsyncSession = Depends(get_db_session),
):
    share_rows_result = await session.execute(
        select(
            DocumentShare.target_tenant_id.label("tenant_id"),
            Tenant.name.label("tenant_name"),
            func.count(DocumentShare.id).label("share_row_count"),
            func.count(func.distinct(DocumentShare.document_id)).label("shared_document_count"),
        )
        .join(Tenant, Tenant.id == DocumentShare.target_tenant_id)
        .group_by(DocumentShare.target_tenant_id, Tenant.name)
        .order_by(Tenant.name.asc())
    )
    share_rows = share_rows_result.all()

    totals_result = await session.execute(
        select(
            func.count(DocumentShare.id).label("share_row_count"),
            func.count(func.distinct(DocumentShare.document_id)).label("shared_document_count"),
        )
    )
    totals_row = totals_result.one()

    audit_counts_result = await session.execute(
        select(AuditLog.action, func.count(AuditLog.id).label("count"))
        .where(AuditLog.action.in_(["document_shares_add", "document_shares_replace", "document_shares_remove"]))
        .group_by(AuditLog.action)
    )
    audit_counts = {row.action: row.count for row in audit_counts_result.all()}

    collector = build_metrics_collector()
    try:
        recent_queries = []
        seen_query_ids: set[str] = set()
        relevant_tenant_ids = {"default"} | {row.tenant_id for row in share_rows}
        for tenant_id in relevant_tenant_ids:
            for metric in await collector.get_recent(tenant_id=tenant_id, limit=recent_limit):
                if metric.query_id in seen_query_ids:
                    continue
                seen_query_ids.add(metric.query_id)
                recent_queries.append(metric)

        tenant_summaries = []
        for row in share_rows:
            denied_visibility_count = 0
            not_found_visibility_count = 0
            get_counter = getattr(collector, "get_counter", None)
            if callable(get_counter):
                denied_visibility_count = await get_counter("document_visibility_denied", row.tenant_id)
                not_found_visibility_count = await get_counter(
                    "document_visibility_not_found", row.tenant_id
                )

            tenant_summaries.append(
                DocumentShareTenantSummaryResponse(
                    tenant_id=row.tenant_id,
                    tenant_name=row.tenant_name,
                    share_row_count=row.share_row_count,
                    shared_document_count=row.shared_document_count,
                    denied_visibility_count=denied_visibility_count,
                    not_found_visibility_count=not_found_visibility_count,
                )
            )

        return DocumentShareSummaryResponse(
            flags=DocumentShareFlagsResponse(
                enable_document_share_management=settings.enable_document_share_management,
                enable_upload_time_document_shares=settings.enable_upload_time_document_shares,
                enable_acl_aware_vector_retrieval=settings.enable_acl_aware_vector_retrieval,
                enable_acl_aware_graph_retrieval=settings.enable_acl_aware_graph_retrieval,
            ),
            totals=DocumentShareTotalsResponse(
                share_row_count=totals_row.share_row_count or 0,
                shared_document_count=totals_row.shared_document_count or 0,
                share_add_audit_count=audit_counts.get("document_shares_add", 0),
                share_replace_audit_count=audit_counts.get("document_shares_replace", 0),
                share_remove_audit_count=audit_counts.get("document_shares_remove", 0),
            ),
            tenants=tenant_summaries,
            query_metrics=DocumentShareQueryMetricsResponse(
                recent_query_count=len(recent_queries),
                shared_hits=sum(getattr(metric, "shared_hits", 0) for metric in recent_queries),
                local_hits=sum(getattr(metric, "local_hits", 0) for metric in recent_queries),
                acl_filtered_results=sum(getattr(metric, "acl_filtered_results", 0) for metric in recent_queries),
            ),
        )
    finally:
        await collector.close()


@router.get(
    "/document-shares/audit",
    response_model=list[DocumentShareAuditEntryResponse],
    summary="Get Recent Document Share Audit Events",
    description="Return recent audit log entries for explicit document share mutations.",
)
async def get_document_share_audit(
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.action.like("document_shares_%"))
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        DocumentShareAuditEntryResponse(
            id=row.id,
            timestamp=row.timestamp,
            actor=row.actor,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            changes=row.changes,
            metadata_json=row.metadata_json,
        )
        for row in rows
    ]


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

    try:
        import redis.asyncio as redis

        from src.api.config import settings as runtime_settings

        r = redis.from_url(runtime_settings.db.redis_url)
        await r.ping()
        await r.close()
        status_report["redis"] = "ok"
    except Exception as e:
        status_report["redis"] = f"error: {str(e)}"

    try:
        neo = platform.neo4j_client
        await neo.verify_connectivity()
        status_report["neo4j"] = "ok"
    except Exception as e:
        status_report["neo4j"] = f"error: {str(e)}"

    return status_report
