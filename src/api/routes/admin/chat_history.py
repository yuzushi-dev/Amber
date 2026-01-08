"""
Chat History Admin Router
==========================

Endpoints for viewing chat conversation history.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.models.feedback import Feedback
from src.core.models.usage import UsageLog

router = APIRouter(prefix="/chat", tags=["Admin - Chat History"])


# =============================================================================
# Response Models
# =============================================================================

class ChatHistoryItem(BaseModel):
    """Single chat history entry."""
    request_id: str
    tenant_id: str
    query_text: str | None = None
    response_preview: str | None = None
    model: str
    provider: str
    total_tokens: int
    cost: float
    has_feedback: bool
    feedback_score: float | None = None
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
    trace_id: str | None = None
    query_text: str | None = None
    response_text: str | None = None
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    feedback: dict | None = None
    metadata: dict
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Endpoints
# =============================================================================

# =============================================================================
# Endpoints
# =============================================================================

@router.get("/history", response_model=ChatHistoryResponse)
async def list_chat_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
):
    """
    List recent chat conversations.
    """
    from src.core.models.memory import ConversationSummary

    try:
        # Build query for conversation summaries
        query = select(ConversationSummary)

        # Filter by tenant if specified
        if tenant_id:
            query = query.where(ConversationSummary.tenant_id == tenant_id)

        # Order by most recent first
        query = query.order_by(desc(ConversationSummary.created_at))

        # Get total count
        count_query = select(func.count(ConversationSummary.id))
        if tenant_id:
            count_query = count_query.where(ConversationSummary.tenant_id == tenant_id)

        total = await session.scalar(count_query) or 0

        # Fetch with pagination
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        rows = result.scalars().all()

        # Build response
        conversations = []
        for conv in rows:
            # Extract query/response from metadata
            metadata = conv.metadata_ or {}
            query_text = metadata.get("query")
            response_text = metadata.get("answer")
            model = metadata.get("model", "default")
            
            # Use title from model or fallback
            # conv.title should be populated
            
            # Create preview
            response_preview = None
            if response_text:
                response_preview = response_text[:100] + "..." if len(response_text) > 100 else response_text
            elif conv.summary:
                response_preview = conv.summary[:100]

            conversations.append(ChatHistoryItem(
                request_id=conv.id,
                tenant_id=conv.tenant_id,
                query_text=query_text or conv.title,
                response_preview=response_preview,
                model=model,
                provider="openai", # Placeholder
                total_tokens=0, # Metrics not linked yet
                cost=0.0,
                has_feedback=False,
                feedback_score=None,
                created_at=conv.created_at,
            ))

        return ChatHistoryResponse(
            conversations=conversations,
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Chat history query failed: {e}")
        return ChatHistoryResponse(
            conversations=[],
            total=0,
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
    """
    from src.core.models.memory import ConversationSummary

    # Query conversation summary
    query = select(ConversationSummary).where(ConversationSummary.id == request_id)
    result = await session.execute(query)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Extract details
    metadata = conv.metadata_ or {}
    query_text = metadata.get("query")
    response_text = metadata.get("answer")
    model = metadata.get("model", "default")

    return ConversationDetail(
        request_id=conv.id,
        tenant_id=conv.tenant_id,
        trace_id=None,
        query_text=query_text or conv.title,
        response_text=response_text or conv.summary,
        model=model,
        provider="openai",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost=0.0,
        feedback=None,
        metadata=metadata,
        created_at=conv.created_at,
    )


@router.delete("/history/{request_id}", status_code=204)
async def delete_conversation(
    request_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a specific conversation.
    """
    from src.core.models.memory import ConversationSummary

    # Query conversation summary
    query = select(ConversationSummary).where(ConversationSummary.id == request_id)
    result = await session.execute(query)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await session.delete(conv)
    await session.commit()
