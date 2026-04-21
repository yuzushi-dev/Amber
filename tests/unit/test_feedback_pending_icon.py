"""
Tests for ZTD-1824: Pending feedback response must include is_positive
so the admin UI can render the correct ThumbsUp/ThumbsDown icon.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.admin_ops.domain.feedback import Feedback


def _make_request(is_super_admin: bool = False):
    req = MagicMock()
    req.state.is_super_admin = is_super_admin
    return req


@pytest.mark.asyncio
async def test_pending_feedback_includes_is_positive():
    """Each item in the pending feedback list must expose is_positive."""
    from src.api.routes.admin.feedback import get_pending_feedback

    pos_feedback = Feedback(
        id="pos-1",
        request_id="req-pos",
        tenant_id="t1",
        is_positive=True,
        score=1.0,
        golden_status="PENDING",
        comment=None,
        metadata_json={},
    )
    neg_feedback = Feedback(
        id="neg-1",
        request_id="req-neg",
        tenant_id="t1",
        is_positive=False,
        score=0.0,
        golden_status="NONE",
        comment="wrong answer",
        metadata_json={},
    )

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(pos_feedback, None), (neg_feedback, None)]
    mock_db.execute.return_value = mock_result

    with patch("src.api.routes.admin.feedback.get_current_tenant", return_value="t1"):
        response = await get_pending_feedback(request=_make_request(), skip=0, limit=50, db=mock_db)

    items = response.data
    assert len(items) == 2

    pos_item = next(i for i in items if i["id"] == "pos-1")
    neg_item = next(i for i in items if i["id"] == "neg-1")

    assert "is_positive" in pos_item, "is_positive must be present in pending feedback response"
    assert pos_item["is_positive"] is True
    assert neg_item["is_positive"] is False


@pytest.mark.asyncio
async def test_pending_feedback_positive_and_negative_both_appear():
    """Both positive and negative feedback enter the pending queue."""
    from src.api.routes.admin.feedback import get_pending_feedback

    feedbacks = [
        Feedback(id="p1", request_id="r1", tenant_id="t1", is_positive=True, score=1.0,
                 golden_status="PENDING", comment=None, metadata_json={}),
        Feedback(id="n1", request_id="r2", tenant_id="t1", is_positive=False, score=0.0,
                 golden_status="NONE", comment="bad", metadata_json={}),
        Feedback(id="p2", request_id="r3", tenant_id="t1", is_positive=True, score=1.0,
                 golden_status="NONE", comment=None, metadata_json={}),
    ]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(f, None) for f in feedbacks]
    mock_db.execute.return_value = mock_result

    with patch("src.api.routes.admin.feedback.get_current_tenant", return_value="t1"):
        response = await get_pending_feedback(request=_make_request(), skip=0, limit=50, db=mock_db)

    items = response.data
    positives = [i for i in items if i.get("is_positive") is True]
    negatives = [i for i in items if i.get("is_positive") is False]

    assert len(positives) == 2
    assert len(negatives) == 1
