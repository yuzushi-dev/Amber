"""
Usage Metrics Service
=====================

Cross-tenant aggregation of LLM token usage from usage_logs.
Used by the super-admin observability endpoint.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.usage import UsageLog
from src.core.tenants.domain.tenant import Tenant


@dataclass
class UsageMetricsFilter:
    tenant_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    operation: str | None = None   # 'generation' | 'embedding' | None = all


@dataclass
class TenantUsageRow:
    tenant_id: str
    tenant_name: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    call_count: int


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    call_count: int = 0


@dataclass
class UsageMetricsResult:
    tenants: list[TenantUsageRow] = field(default_factory=list)
    totals: UsageTotals = field(default_factory=UsageTotals)


class UsageMetricsService:
    """
    Aggregates usage_logs by tenant with optional filters.

    Joins with the tenants table to resolve tenant names.
    Super-admin only — caller is responsible for auth.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_tenant_aggregates(self, f: UsageMetricsFilter) -> UsageMetricsResult:
        """
        Return per-tenant token usage aggregated from usage_logs.

        Applies optional filters for tenant, date range, and operation type.
        Results are sorted by total_tokens descending.
        """
        stmt = (
            select(
                UsageLog.tenant_id,
                Tenant.name.label("tenant_name"),
                func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(UsageLog.cost), 0.0).label("cost"),
                func.count(UsageLog.id).label("call_count"),
            )
            .outerjoin(Tenant, Tenant.id == UsageLog.tenant_id)
            .group_by(UsageLog.tenant_id, Tenant.name)
            .order_by(func.sum(UsageLog.total_tokens).desc())
        )

        if f.tenant_id:
            stmt = stmt.where(UsageLog.tenant_id == f.tenant_id)
        if f.start_date:
            stmt = stmt.where(UsageLog.created_at >= f.start_date)
        if f.end_date:
            stmt = stmt.where(UsageLog.created_at <= f.end_date)
        if f.operation:
            stmt = stmt.where(UsageLog.operation == f.operation)

        result = await self._session.execute(stmt)
        rows = result.all()

        tenant_rows = [
            TenantUsageRow(
                tenant_id=row.tenant_id,
                tenant_name=row.tenant_name,
                input_tokens=int(row.input_tokens),
                output_tokens=int(row.output_tokens),
                total_tokens=int(row.total_tokens),
                cost=float(row.cost),
                call_count=int(row.call_count),
            )
            for row in rows
        ]

        totals = UsageTotals(
            input_tokens=sum(r.input_tokens for r in tenant_rows),
            output_tokens=sum(r.output_tokens for r in tenant_rows),
            total_tokens=sum(r.total_tokens for r in tenant_rows),
            cost=sum(r.cost for r in tenant_rows),
            call_count=sum(r.call_count for r in tenant_rows),
        )

        return UsageMetricsResult(tenants=tenant_rows, totals=totals)
