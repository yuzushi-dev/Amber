"""
Feedback API Routes
===================

Endpoints for capturing user feedback on RAG responses.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.api.schemas.base import ResponseSchema
from src.core.models.feedback import Feedback
from src.shared.context import get_current_tenant
from src.core.rate_limiter import rate_limiter, RateLimitCategory
from src.core.services.tuning import TuningService
from src.core.database.session import async_session_maker

router = APIRouter(prefix="/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)

from pydantic import BaseModel

class FeedbackCreate(BaseModel):
    request_id: str
    is_positive: bool
    score: Optional[float] = None
    comment: Optional[str] = None
    correction: Optional[str] = None
    metadata: Dict[str, Any] = {}

class FeedbackResponse(BaseModel):
    id: str
    request_id: str
    is_positive: bool
    comment: Optional[str] = None

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
            is_positive=data.is_positive
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
        )

@router.get("/{request_id}", response_model=ResponseSchema[List[FeedbackResponse]])
async def get_feedback(
    request_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get all feedback for a specific request.
    """
    from sqlalchemy import select
    
    result = await db.execute(
        select(Feedback).where(Feedback.request_id == request_id)
    )
    feedbacks = result.scalars().all()
    
    return ResponseSchema(
        data=[
            FeedbackResponse(
                id=f.id,
                request_id=f.request_id,
                is_positive=f.is_positive,
                comment=f.comment
            )
            for f in feedbacks
        ]
    )
