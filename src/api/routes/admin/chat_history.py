"""
Chat History Admin Router
==========================

Endpoints for viewing chat conversation history.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime

from src.core.database.session import get_db_session
from src.core.models.usage import UsageLog
from src.core.models.feedback import Feedback

router = APIRouter(prefix="/admin/chat", tags=["Admin - Chat History"])


# =============================================================================
# Response Models
# =============================================================================

class ChatHistoryItem(BaseModel):
    """Single chat history entry."""
    request_id: str
    tenant_id: str
    query_text: Optional[str] = None
    response_preview: Optional[str] = None
    model: str
    provider: str
    total_tokens: int
    cost: float
    has_feedback: bool
    feedback_score: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    """Paginated chat history."""
    conversations: list[ChatHistoryItem]
    total: int
    limit: int
    offset: int


class ConversationDetail(BaseModel):
    """Full conversation details."""
    request_id: str
    tenant_id: str
    trace_id: Optional[str] = None
    query_text: Optional[str] = None
    response_text: Optional[str] = None
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    feedback: Optional[dict] = None
    metadata: dict
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/history", response_model=ChatHistoryResponse)
async def list_chat_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_db_session),
):
    """
    List recent chat conversations.

    Retrieves generation operations from UsageLog with optional feedback data.
    """
    # Build query for generation operations
    query = (
        select(UsageLog, Feedback)
        .outerjoin(Feedback, UsageLog.request_id == Feedback.request_id)
        .where(UsageLog.operation == "generation")
    )

    # Filter by tenant if specified
    if tenant_id:
        query = query.where(UsageLog.tenant_id == tenant_id)

    # Order by most recent first
    query = query.order_by(desc(UsageLog.created_at))

    # Get total count
    count_query = (
        select(func.count(UsageLog.id))
        .where(UsageLog.operation == "generation")
    )
    if tenant_id:
        count_query = count_query.where(UsageLog.tenant_id == tenant_id)

    total = await session.scalar(count_query) or 0

    # Fetch with pagination
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    rows = result.all()

    # Build response
    conversations = []
    for usage_log, feedback in rows:
        # Extract query/response from metadata
        metadata = usage_log.metadata_json or {}
        query_text = metadata.get("query_text") or metadata.get("query")
        response_text = metadata.get("response_text") or metadata.get("response")

        # Create preview (first 100 chars)
        response_preview = None
        if response_text:
            response_preview = response_text[:100] + "..." if len(response_text) > 100 else response_text

        conversations.append(ChatHistoryItem(
            request_id=usage_log.request_id or usage_log.id,
            tenant_id=usage_log.tenant_id,
            query_text=query_text,
            response_preview=response_preview,
            model=usage_log.model,
            provider=usage_log.provider,
            total_tokens=usage_log.total_tokens or 0,
            cost=usage_log.cost or 0.0,
            has_feedback=feedback is not None,
            feedback_score=feedback.score if feedback else None,
            created_at=usage_log.created_at,
        ))

    return ChatHistoryResponse(
        conversations=conversations,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/history/{request_id}", response_model=ConversationDetail)
async def get_conversation_detail(
    request_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get full details for a specific conversation.

    Includes complete query, response, tokens, cost, and feedback.
    """
    # Query usage log
    usage_query = (
        select(UsageLog)
        .where(UsageLog.request_id == request_id)
        .where(UsageLog.operation == "generation")
    )
    result = await session.execute(usage_query)
    usage_log = result.scalar_one_or_none()

    if not usage_log:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Query feedback
    feedback_query = select(Feedback).where(Feedback.request_id == request_id)
    feedback_result = await session.execute(feedback_query)
    feedback = feedback_result.scalar_one_or_none()

    # Extract query/response from metadata
    metadata = usage_log.metadata_json or {}
    query_text = metadata.get("query_text") or metadata.get("query")
    response_text = metadata.get("response_text") or metadata.get("response")

    # Build feedback dict
    feedback_data = None
    if feedback:
        feedback_data = {
            "score": feedback.score,
            "is_positive": feedback.is_positive,
            "comment": feedback.comment,
            "correction": feedback.correction,
            "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
        }

    return ConversationDetail(
        request_id=usage_log.request_id or usage_log.id,
        tenant_id=usage_log.tenant_id,
        trace_id=usage_log.trace_id,
        query_text=query_text,
        response_text=response_text,
        model=usage_log.model,
        provider=usage_log.provider,
        input_tokens=usage_log.input_tokens or 0,
        output_tokens=usage_log.output_tokens or 0,
        total_tokens=usage_log.total_tokens or 0,
        cost=usage_log.cost or 0.0,
        feedback=feedback_data,
        metadata=metadata,
        created_at=usage_log.created_at,
    )
