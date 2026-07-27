"""
Integration + HTTP endpoint tests for cross-tenant usage metrics.
Requires running DB (uses db_session fixture from integration/conftest.py).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.usage import UsageLog


def make_usage_log(tenant_id, provider="ollama", model="gemma4:31b-cloud",
                   operation="generation", input_tokens=100, output_tokens=50,
                   cost=0.001, created_at=None):
    return UsageLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        provider=provider,
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost=cost,
        metadata_json={},
        created_at=created_at or datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_aggregate_two_tenants(db_session: AsyncSession):
    from src.core.admin_ops.application.usage_metrics_service import (
        UsageMetricsFilter,
        UsageMetricsService,
    )
    tid_a = f"test_um_a_{uuid.uuid4().hex[:8]}"
    tid_b = f"test_um_b_{uuid.uuid4().hex[:8]}"

    db_session.add_all([
        make_usage_log(tid_a, input_tokens=500, output_tokens=200, cost=0.01),
        make_usage_log(tid_a, input_tokens=300, output_tokens=100, cost=0.005),
        make_usage_log(tid_b, input_tokens=100, output_tokens=50, cost=0.002),
    ])
    await db_session.commit()

    result = await UsageMetricsService(db_session).get_tenant_aggregates(
        UsageMetricsFilter(tenant_id=tid_a)
    )

    rows = {r.tenant_id: r for r in result.tenants}
    assert tid_a in rows
    assert tid_b not in rows
    assert rows[tid_a].input_tokens == 800
    assert rows[tid_a].output_tokens == 300
    assert rows[tid_a].call_count == 2
    assert abs(rows[tid_a].cost - 0.015) < 1e-9


@pytest.mark.asyncio
async def test_date_filter(db_session: AsyncSession):
    from src.core.admin_ops.application.usage_metrics_service import (
        UsageMetricsFilter,
        UsageMetricsService,
    )
    tid = f"test_um_date_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    db_session.add_all([
        make_usage_log(tid, input_tokens=100, created_at=now - timedelta(days=10)),
        make_usage_log(tid, input_tokens=200, created_at=now - timedelta(days=2)),
        make_usage_log(tid, input_tokens=300, created_at=now - timedelta(hours=1)),
    ])
    await db_session.commit()

    result = await UsageMetricsService(db_session).get_tenant_aggregates(
        UsageMetricsFilter(
            tenant_id=tid,
            start_date=now - timedelta(days=3),
            end_date=now + timedelta(hours=1),
        )
    )
    rows = {r.tenant_id: r for r in result.tenants}
    assert rows[tid].input_tokens == 500
    assert rows[tid].call_count == 2


@pytest.mark.asyncio
async def test_operation_filter(db_session: AsyncSession):
    from src.core.admin_ops.application.usage_metrics_service import (
        UsageMetricsFilter,
        UsageMetricsService,
    )
    tid = f"test_um_op_{uuid.uuid4().hex[:8]}"

    db_session.add_all([
        make_usage_log(tid, operation="generation", input_tokens=500),
        make_usage_log(tid, operation="generation", input_tokens=300),
        make_usage_log(tid, operation="embedding", input_tokens=100),
    ])
    await db_session.commit()

    gen = await UsageMetricsService(db_session).get_tenant_aggregates(
        UsageMetricsFilter(tenant_id=tid, operation="generation")
    )
    emb = await UsageMetricsService(db_session).get_tenant_aggregates(
        UsageMetricsFilter(tenant_id=tid, operation="embedding")
    )

    assert {r.tenant_id: r for r in gen.tenants}[tid].call_count == 2
    assert {r.tenant_id: r for r in emb.tenants}[tid].call_count == 1
