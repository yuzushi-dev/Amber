"""
Feedback API Routes
===================

Endpoints for capturing user feedback on RAG responses.
"""

import logging
from typing import Any
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session as get_db
from src.api.schemas.base import ResponseSchema
from src.core.database.session import async_session_maker
from src.core.models.feedback import Feedback
from src.core.rate_limiter import RateLimitCategory, rate_limiter
from src.core.services.tuning import TuningService
from src.shared.context import get_current_tenant

router = APIRouter(prefix="/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)

# from pydantic import BaseModel # Moved to top


class FeedbackCreate(BaseModel):
    request_id: str
    is_positive: bool
    score: float | None = None
    comment: str | None = None
    correction: str | None = None
    metadata: dict[str, Any] = {}

class FeedbackResponse(BaseModel):
    id: str
    request_id: str
    is_positive: bool
    comment: str | None = None

@router.post("/", response_model=ResponseSchema[FeedbackResponse])
async def create_feedback(
    data: FeedbackCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Submit feedback for a RAG response.
    """
    tenant_id = get_current_tenant() or "default"

    # Safety Check: Rate Limit for Feedback
    rl_result = await rate_limiter.check(str(tenant_id), RateLimitCategory.GENERAL)
    if not rl_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many feedback submissions. Please try again later."
        )

    try:
        feedback = Feedback(
            tenant_id=tenant_id,
            request_id=data.request_id,
            is_positive=data.is_positive,
            score=data.score if data.score is not None else (1.0 if data.is_positive else 0.0),
            comment=data.comment,
            correction=data.correction,
            metadata_json=data.metadata
        )
        db.add(feedback)
        await db.commit()
        await db.refresh(feedback)

        # Stage 8.5.2: Wire feedback to weight adjustments (Analysis)
        tuning = TuningService(session_factory=async_session_maker)
        await tuning.analyze_feedback_for_tuning(
            tenant_id=tenant_id,
            request_id=data.request_id,
            is_positive=data.is_positive,
            comment=data.comment,
            selected_snippets=data.metadata.get("selected_snippets")
        )

        return ResponseSchema(
            data=FeedbackResponse(
                id=feedback.id,
                request_id=feedback.request_id,
                is_positive=feedback.is_positive,
                comment=feedback.comment
            ),
            message="Feedback submitted successfully"
        )
    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit feedback"
        ) from e

@router.get("/{request_id}", response_model=ResponseSchema[dict])
async def get_feedback(
    request_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """
    Get feedback for a specific request with pagination.

    Args:
        request_id: Request UUID
        limit: Maximum number of feedback items to return (default: 50)
        offset: Number of feedback items to skip (default: 0)

    Returns:
        Paginated feedback response with items, total, limit, and offset
    """
    from sqlalchemy import func, select

    # Get total count
    count_stmt = select(func.count(Feedback.id)).where(Feedback.request_id == request_id)
    total = await db.scalar(count_stmt)

    # Fetch feedback with pagination
    result = await db.execute(
        select(Feedback)
        .where(Feedback.request_id == request_id)
        .order_by(Feedback.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    feedbacks = result.scalars().all()

    return ResponseSchema(
        data={
            "items": [
                FeedbackResponse(
                    id=f.id,
                    request_id=f.request_id,
                    is_positive=f.is_positive,
                    comment=f.comment
                )
                for f in feedbacks
            ],
            "total": total or 0,
            "limit": limit,
            "offset": offset
        }
    )
