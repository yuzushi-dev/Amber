"""
Feedback API Routes
===================

Endpoints for capturing user feedback on RAG responses.
"""

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import settings
from src.api.deps import get_db_session as get_db
from src.api.schemas.base import ResponseSchema
from src.core.admin_ops.domain.feedback import Feedback
from src.core.admin_ops.infrastructure.rate_limiter import RateLimitCategory, get_rate_limiter
from src.core.generation.domain.memory_models import ConversationSummary
from src.shared.context import get_current_tenant

router = APIRouter(prefix="/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)

# Rate limiter factory
_rate_limiter = None


def _get_rate_limiter_instance():
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = get_rate_limiter(
            redis_url=settings.db.redis_url,
            requests_per_minute=settings.rate_limits.requests_per_minute,
            queries_per_minute=settings.rate_limits.queries_per_minute,
            uploads_per_hour=settings.rate_limits.uploads_per_hour,
        )
    return _rate_limiter


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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit feedback for a RAG response.
    """
    tenant_id = getattr(request.state, "tenant_id", None) or get_current_tenant()
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: tenant context missing.",
        )
    tenant_id = str(tenant_id)
    api_key_id = getattr(request.state, "api_key_id", None)
    if not api_key_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: authenticated API key missing.",
        )

    # Safety Check: Rate Limit for Feedback
    rl_result = await _get_rate_limiter_instance().check(str(tenant_id), RateLimitCategory.GENERAL)
    if not rl_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many feedback submissions. Please try again later.",
        )

    try:
        from sqlalchemy import select

        owner_result = await db.execute(
            select(ConversationSummary).where(
                ConversationSummary.id == data.request_id,
                ConversationSummary.tenant_id == tenant_id,
            )
        )
        owner_summary = owner_result.scalar_one_or_none()
        if owner_summary is not None and owner_summary.api_key_id != api_key_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

        # Look for an existing PENDING/NONE record for this (request_id, tenant_id).
        # VERIFIED and REJECTED records are never modified.
        existing_stmt = select(Feedback).where(
                Feedback.request_id == data.request_id,
                Feedback.tenant_id == tenant_id,
                Feedback.api_key_id == api_key_id,
                Feedback.golden_status.in_(["NONE", "PENDING"]),
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        # existing is only a PENDING/NONE record (VERIFIED/REJECTED excluded by query)
        if existing is not None and existing.is_positive == data.is_positive:
            # Same polarity: update in place and re-queue for review
            existing.comment = data.comment
            existing.correction = data.correction
            existing.score = data.score if data.score is not None else existing.score
            existing.golden_status = "PENDING"
            if data.metadata:
                existing.metadata_json = {**(existing.metadata_json or {}), **data.metadata}
            feedback = existing
        elif existing is not None:
            # Polarity flip: remove old PENDING/NONE record, create fresh PENDING
            await db.delete(existing)
            feedback = Feedback(
                id=str(uuid4()),
                tenant_id=tenant_id,
                request_id=data.request_id,
                api_key_id=api_key_id,
                is_positive=data.is_positive,
                score=data.score if data.score is not None else (1.0 if data.is_positive else 0.0),
                comment=data.comment,
                correction=data.correction,
                metadata_json=data.metadata,
                golden_status="PENDING",
            )
            db.add(feedback)
        else:
            # No editable record (none exists or only VERIFIED/REJECTED): create new PENDING
            feedback = Feedback(
                id=str(uuid4()),
                tenant_id=tenant_id,
                request_id=data.request_id,
                api_key_id=api_key_id,
                is_positive=data.is_positive,
                score=data.score if data.score is not None else (1.0 if data.is_positive else 0.0),
                comment=data.comment,
                correction=data.correction,
                metadata_json=data.metadata,
                golden_status="PENDING",
            )
            db.add(feedback)

        await db.commit()
        await db.refresh(feedback)

        return ResponseSchema(
            data=FeedbackResponse(
                id=feedback.id,
                request_id=feedback.request_id,
                is_positive=feedback.is_positive,
                comment=feedback.comment,
            ),
            message="Feedback submitted successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to submit feedback"
        ) from e


@router.get("/{request_id}", response_model=ResponseSchema[dict])
async def get_feedback(
    request_id: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
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

    tenant_id = getattr(request.state, "tenant_id", None) or get_current_tenant()
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: tenant context missing.",
        )
    api_key_id = getattr(request.state, "api_key_id", None)
    if not api_key_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: authenticated API key missing.",
        )

    owner_result = await db.execute(
        select(ConversationSummary).where(
            ConversationSummary.id == request_id,
            ConversationSummary.tenant_id == tenant_id,
        )
    )
    owner_summary = owner_result.scalar_one_or_none()
    if owner_summary is not None and owner_summary.api_key_id != api_key_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    # Get total count — scoped to caller's tenant
    count_stmt = select(func.count(Feedback.id)).where(
        Feedback.request_id == request_id,
        Feedback.tenant_id == tenant_id,
        Feedback.api_key_id == api_key_id,
    )
    total = await db.scalar(count_stmt)

    # Fetch feedback with pagination — scoped to caller's tenant
    result = await db.execute(
        select(Feedback)
        .where(
            Feedback.request_id == request_id,
            Feedback.tenant_id == tenant_id,
            Feedback.api_key_id == api_key_id,
        )
        .order_by(Feedback.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    feedbacks = result.scalars().all()

    return ResponseSchema(
        data={
            "items": [
                FeedbackResponse(
                    id=f.id, request_id=f.request_id, is_positive=f.is_positive, comment=f.comment
                )
                for f in feedbacks
            ],
            "total": total or 0,
            "limit": limit,
            "offset": offset,
        }
    )
