"""
Unit tests for UsageMetricsService — no DB required.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class TestUsageMetricsService:

    @pytest.mark.asyncio
    async def test_aggregate_all_tenants(self):
        from src.core.admin_ops.application.usage_metrics_service import (
            UsageMetricsFilter, UsageMetricsService,
        )
        mock_session = AsyncMock(spec=AsyncSession)
        row_a = MagicMock(tenant_id="tenant-a", tenant_name="Tenant A",
                          input_tokens=1000, output_tokens=500,
                          total_tokens=1500, cost=0.05, call_count=10)
        row_b = MagicMock(tenant_id="tenant-b", tenant_name="Tenant B",
                          input_tokens=200, output_tokens=100,
                          total_tokens=300, cost=0.01, call_count=2)
        mock_result = MagicMock()
        mock_result.all.return_value = [row_a, row_b]
        mock_session.execute.return_value = mock_result

        result = await UsageMetricsService(mock_session).get_tenant_aggregates(UsageMetricsFilter())

        assert len(result.tenants) == 2
        assert result.tenants[0].tenant_id == "tenant-a"
        assert result.totals.input_tokens == 1200
        assert result.totals.output_tokens == 600
        assert result.totals.call_count == 12

    @pytest.mark.asyncio
    async def test_filter_by_tenant_id(self):
        from src.core.admin_ops.application.usage_metrics_service import (
            UsageMetricsFilter, UsageMetricsService,
        )
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        await UsageMetricsService(mock_session).get_tenant_aggregates(
            UsageMetricsFilter(tenant_id="specific-tenant")
        )
        assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_filter_by_date_range(self):
        from src.core.admin_ops.application.usage_metrics_service import (
            UsageMetricsFilter, UsageMetricsService,
        )
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        now = datetime.now(UTC)
        result = await UsageMetricsService(mock_session).get_tenant_aggregates(
            UsageMetricsFilter(start_date=now - timedelta(days=7), end_date=now)
        )
        assert result.tenants == []
        assert result.totals.call_count == 0

    @pytest.mark.asyncio
    async def test_filter_by_operation(self):
        from src.core.admin_ops.application.usage_metrics_service import (
            UsageMetricsFilter, UsageMetricsService,
        )
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await UsageMetricsService(mock_session).get_tenant_aggregates(
            UsageMetricsFilter(operation="generation")
        )
        assert result.tenants == []

    @pytest.mark.asyncio
    async def test_empty_result_returns_zero_totals(self):
        from src.core.admin_ops.application.usage_metrics_service import (
            UsageMetricsFilter, UsageMetricsService,
        )
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await UsageMetricsService(mock_session).get_tenant_aggregates(UsageMetricsFilter())
        assert result.tenants == []
        assert result.totals.input_tokens == 0
        assert result.totals.output_tokens == 0
        assert result.totals.cost == 0.0
        assert result.totals.call_count == 0

    @pytest.mark.asyncio
    async def test_totals_computed_from_rows(self):
        from src.core.admin_ops.application.usage_metrics_service import (
            UsageMetricsFilter, UsageMetricsService,
        )
        mock_session = AsyncMock(spec=AsyncSession)
        rows = [
            MagicMock(tenant_id=f"t{i}", tenant_name=f"T{i}",
                      input_tokens=100, output_tokens=50,
                      total_tokens=150, cost=0.01, call_count=5)
            for i in range(3)
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        result = await UsageMetricsService(mock_session).get_tenant_aggregates(UsageMetricsFilter())
        assert result.totals.input_tokens == 300
        assert result.totals.output_tokens == 150
        assert result.totals.total_tokens == 450
        assert abs(result.totals.cost - 0.03) < 1e-9
        assert result.totals.call_count == 15
