"""
Tests for ZTD-1823: Allow multiple feedback submissions for the same answer.

Rules:
- Same polarity re-submit: upsert (update the existing PENDING/NONE record)
- Polarity flip: delete existing PENDING/NONE + create new
- VERIFIED/REJECTED records are never modified; a new PENDING record is created
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.admin_ops.domain.feedback import Feedback


def _make_existing_feedback(
    request_id: str = "req-1",
    tenant_id: str = "t1",
    is_positive: bool = True,
    golden_status: str = "PENDING",
) -> Feedback:
    return Feedback(
        id="existing-fb",
        request_id=request_id,
        tenant_id=tenant_id,
        is_positive=is_positive,
        score=1.0 if is_positive else 0.0,
        golden_status=golden_status,
        comment=None,
        metadata_json={},
    )


def _mock_db_with_existing(existing: Feedback | None):
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=existing)
    mock_db.execute.return_value = mock_result
    # session.add() is synchronous in SQLAlchemy (even async sessions)
    mock_db.add = MagicMock()
    return mock_db


@pytest.mark.asyncio
async def test_same_polarity_updates_existing_pending():
    """Re-submitting with same polarity updates the existing PENDING record."""
    from src.api.routes.feedback import create_feedback, FeedbackCreate

    existing = _make_existing_feedback(is_positive=True, golden_status="PENDING")
    mock_db = _mock_db_with_existing(existing)
    mock_db.refresh = AsyncMock()

    mock_request = MagicMock()
    mock_request.state.tenant_id = "t1"

    data = FeedbackCreate(
        request_id="req-1",
        is_positive=True,
        score=1.0,
        comment="Updated comment",
    )

    with patch("src.api.routes.feedback.get_current_tenant", return_value="t1"):
        with patch("src.api.routes.feedback._get_rate_limiter_instance") as mock_rl:
            mock_rl.return_value.check = AsyncMock(return_value=MagicMock(allowed=True))
            response = await create_feedback(data=data, request=mock_request, db=mock_db)

    # Should NOT have added a new record
    mock_db.add.assert_not_called()
    # Should have updated the existing record's comment and re-queued for review
    assert existing.comment == "Updated comment"
    assert existing.golden_status == "PENDING"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_polarity_flip_deletes_old_creates_new():
    """Flipping polarity on a PENDING record: delete old, create new."""
    from src.api.routes.feedback import create_feedback, FeedbackCreate

    existing = _make_existing_feedback(is_positive=True, golden_status="PENDING")
    mock_db = _mock_db_with_existing(existing)
    mock_db.refresh = AsyncMock()

    mock_request = MagicMock()
    mock_request.state.tenant_id = "t1"

    data = FeedbackCreate(
        request_id="req-1",
        is_positive=False,  # flipped
        score=0.0,
        comment="Actually bad",
    )

    with patch("src.api.routes.feedback.get_current_tenant", return_value="t1"):
        with patch("src.api.routes.feedback._get_rate_limiter_instance") as mock_rl:
            mock_rl.return_value.check = AsyncMock(return_value=MagicMock(allowed=True))
            response = await create_feedback(data=data, request=mock_request, db=mock_db)

    # Old record must be deleted
    mock_db.delete.assert_called_once_with(existing)
    # New record must be added
    mock_db.add.assert_called_once()
    new_feedback = mock_db.add.call_args[0][0]
    assert new_feedback.is_positive is False
    assert new_feedback.comment == "Actually bad"


@pytest.mark.asyncio
async def test_no_existing_feedback_creates_new():
    """No prior feedback: create a new record as before."""
    from src.api.routes.feedback import create_feedback, FeedbackCreate

    mock_db = _mock_db_with_existing(None)
    mock_db.refresh = AsyncMock()

    mock_request = MagicMock()
    mock_request.state.tenant_id = "t1"

    data = FeedbackCreate(request_id="req-new", is_positive=True, score=1.0)

    with patch("src.api.routes.feedback.get_current_tenant", return_value="t1"):
        with patch("src.api.routes.feedback._get_rate_limiter_instance") as mock_rl:
            mock_rl.return_value.check = AsyncMock(return_value=MagicMock(allowed=True))
            response = await create_feedback(data=data, request=mock_request, db=mock_db)

    mock_db.add.assert_called_once()
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_verified_feedback_always_creates_new():
    """If only VERIFIED feedback exists, the query (filtered to NONE/PENDING) returns None.
    A new PENDING record must be created without touching the VERIFIED one."""
    from src.api.routes.feedback import create_feedback, FeedbackCreate

    # SQL query filters golden_status IN ('NONE', 'PENDING') — VERIFIED is excluded,
    # so the DB returns None even though a VERIFIED record exists.
    mock_db = _mock_db_with_existing(None)
    mock_db.refresh = AsyncMock()

    mock_request = MagicMock()
    mock_request.state.tenant_id = "t1"

    data = FeedbackCreate(request_id="req-1", is_positive=True, score=1.0, comment="Re-confirm")

    with patch("src.api.routes.feedback.get_current_tenant", return_value="t1"):
        with patch("src.api.routes.feedback._get_rate_limiter_instance") as mock_rl:
            mock_rl.return_value.check = AsyncMock(return_value=MagicMock(allowed=True))
            response = await create_feedback(data=data, request=mock_request, db=mock_db)

    # No existing PENDING record to delete
    mock_db.delete.assert_not_called()
    # New PENDING record created
    mock_db.add.assert_called_once()
    new_feedback = mock_db.add.call_args[0][0]
    assert new_feedback.golden_status == "PENDING"
    assert new_feedback.comment == "Re-confirm"
