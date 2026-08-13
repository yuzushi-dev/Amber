"""
Tests for ZTD-1818: Admin feedback endpoint must be scoped to their tenant.
Super admins get cross-tenant visibility; regular admins see only their own tenant.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.admin_ops.domain.feedback import Feedback


def _make_request(is_super_admin: bool = False, tenant_id: str = "t1"):
    req = MagicMock()
    req.state.is_super_admin = is_super_admin
    req.state.tenant_id = tenant_id
    req.state.permissions = ["super_admin"] if is_super_admin else ["admin"]
    return req


def _make_feedbacks(tenant_ids: list[str]) -> list[tuple]:
    rows = []
    for i, tid in enumerate(tenant_ids):
        f = Feedback(
            id=f"fb-{i}",
            request_id=f"req-{i}",
            tenant_id=tid,
            is_positive=True,
            score=1.0,
            golden_status="PENDING",
            comment=None,
            metadata_json={},
        )
        rows.append((f, None))
    return rows


@pytest.mark.asyncio
async def test_tenant_admin_query_includes_tenant_filter():
    """A regular tenant admin's DB query must include a tenant_id WHERE clause."""

    from src.api.routes.admin.feedback import get_pending_feedback

    # Simulate DB returning only t1 rows (as real SQL filter would produce)
    rows = _make_feedbacks(["t1", "t1"])
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_db.execute.return_value = mock_result

    request = _make_request(is_super_admin=False, tenant_id="t1")

    with patch("src.api.routes.admin.feedback.get_current_tenant", return_value="t1"):
        response = await get_pending_feedback(request=request, skip=0, limit=50, db=mock_db)

    # Verify the query was actually executed (not skipped)
    mock_db.execute.assert_called_once()

    # Verify the compiled query string contains a tenant filter
    executed_query = mock_db.execute.call_args[0][0]
    compiled = str(executed_query.compile(compile_kwargs={"literal_binds": True}))
    assert "tenant_id" in compiled, "Non-super-admin query must filter by tenant_id"

    # Response must include tenant_id field
    assert all("tenant_id" in item for item in response.data)


@pytest.mark.asyncio
async def test_super_admin_sees_all_tenants():
    """A super admin must receive feedback from all tenants plus tenant_id in each item."""
    from src.api.routes.admin.feedback import get_pending_feedback

    rows = _make_feedbacks(["t1", "t2", "t3"])
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_db.execute.return_value = mock_result

    request = _make_request(is_super_admin=True, tenant_id="t1")

    with patch("src.api.routes.admin.feedback.get_current_tenant", return_value="t1"):
        response = await get_pending_feedback(request=request, skip=0, limit=50, db=mock_db)

    items = response.data
    assert len(items) == 3

    tenant_ids_in_response = {item.get("tenant_id") for item in items}
    assert tenant_ids_in_response == {"t1", "t2", "t3"}, (
        "Super admin response must include tenant_id for each item"
    )


@pytest.mark.asyncio
async def test_response_includes_tenant_id_field():
    """The pending feedback response must always include tenant_id for admin visibility."""
    from src.api.routes.admin.feedback import get_pending_feedback

    rows = _make_feedbacks(["t1"])
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_db.execute.return_value = mock_result

    request = _make_request(is_super_admin=False, tenant_id="t1")

    with patch("src.api.routes.admin.feedback.get_current_tenant", return_value="t1"):
        response = await get_pending_feedback(request=request, skip=0, limit=50, db=mock_db)

    assert len(response.data) == 1
    assert "tenant_id" in response.data[0], "tenant_id must be present in feedback response"


@pytest.mark.asyncio
async def test_pending_feedback_joins_legacy_rows_when_both_owners_are_null():
    """Tenant-scoped admins must retain the feedback/conversation association."""
    from src.api.routes.admin.feedback import get_pending_feedback

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await get_pending_feedback(
        request=_make_request(is_super_admin=False, tenant_id="t1"),
        skip=0,
        limit=50,
        db=mock_db,
    )

    stmt = mock_db.execute.call_args.args[0]
    join_sql = str(
        stmt.get_final_froms()[0].onclause.compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "feedbacks.tenant_id = conversation_summaries.tenant_id" in join_sql
    assert "api_key_id" not in join_sql
