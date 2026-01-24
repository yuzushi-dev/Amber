"""
Chat History Admin Router
==========================

Endpoints for viewing chat conversation history.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.admin_ops.domain.feedback import Feedback
from src.core.admin_ops.domain.usage import UsageLog

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
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
):
    """
    List recent chat conversations.
    
    Privacy Rules:
    - Admins can see metadata for all conversations.
    - Query/Response content is REDACTED unless the conversation has user feedback.
    """
    from src.core.generation.domain.memory_models import ConversationSummary

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
        
        # Fetch QueryMetrics for cost/token data
        from src.api.config import settings
        from src.core.admin_ops.application.metrics.collector import MetricsCollector
        
        collector = MetricsCollector(redis_url=settings.db.redis_url)
        all_metrics = await collector.get_recent(tenant_id=tenant_id, limit=500)
        
        # Build a lookup by conversation_id
        metrics_by_conv: dict[str, dict] = {}
        for m in all_metrics:
            if m.conversation_id:
                if m.conversation_id not in metrics_by_conv:
                    metrics_by_conv[m.conversation_id] = {
                        "total_tokens": 0,
                        "cost": 0.0,
                        "model": m.model,
                        "provider": m.provider,
                    }
                metrics_by_conv[m.conversation_id]["total_tokens"] += m.tokens_used
                metrics_by_conv[m.conversation_id]["cost"] += m.cost_estimate
        
        # Fetch all conversation IDs with feedback for bulk lookup
        conv_ids = [conv.id for conv in rows]
        feedback_query = select(Feedback.request_id).where(
            Feedback.request_id.in_(conv_ids)
        ).distinct()
        feedback_result = await session.execute(feedback_query)
        conversations_with_feedback = {row[0] for row in feedback_result.fetchall()}
        
        for conv in rows:
            # Extract query/response from metadata
            metadata = conv.metadata_ or {}
            query_text = metadata.get("query")
            response_text = metadata.get("answer")
            model = metadata.get("model", "default")
            
            # PRIVACY REDACTION: Only show content if conversation has feedback
            has_feedback = conv.id in conversations_with_feedback
            if not has_feedback:
                query_text = "[REDACTED - PRIVACY]"
                response_text = "[REDACTED - PRIVACY]"
            
            # Create preview
            response_preview = None
            if response_text:
                response_preview = response_text[:100] + "..." if len(response_text) > 100 else response_text
            elif conv.summary and has_feedback:
                response_preview = conv.summary[:100]
            elif not has_feedback:
                response_preview = "[REDACTED - PRIVACY]"

            # Get metrics from lookup
            conv_metrics = metrics_by_conv.get(conv.id, {})
            total_tokens = conv_metrics.get("total_tokens", 0)
            cost = conv_metrics.get("cost", 0.0)
            if conv_metrics.get("model"):
                model = conv_metrics["model"]
            provider = conv_metrics.get("provider", "openai")

            conversations.append(ChatHistoryItem(
                request_id=conv.id,
                tenant_id=conv.tenant_id,
                query_text=query_text or conv.title if has_feedback else "[REDACTED - PRIVACY]",
                response_preview=response_preview,
                model=model,
                provider=provider,
                total_tokens=total_tokens,
                cost=cost,
                has_feedback=has_feedback,
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
        import traceback
        logging.getLogger(__name__).error(f"Chat history query failed: {e}\n{traceback.format_exc()}")
        return ChatHistoryResponse(
            conversations=[],
            total=0,
            limit=limit,
            offset=offset,
        )


@router.get("/history/{request_id}", response_model=ConversationDetail)
async def get_conversation_detail(
    request_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get full details for a specific conversation.
    
    Privacy Rules:
    - Query/Response content is REDACTED unless the conversation has user feedback.
    """
    from src.core.generation.domain.memory_models import ConversationSummary

    # Query conversation summary
    query = select(ConversationSummary).where(ConversationSummary.id == request_id)
    result = await session.execute(query)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if conversation has feedback
    feedback_query = select(Feedback).where(Feedback.conversation_id == request_id).limit(1)
    feedback_result = await session.execute(feedback_query)
    has_feedback = feedback_result.scalar_one_or_none() is not None

    # Extract details
    metadata = conv.metadata_ or {}
    query_text = metadata.get("query")
    response_text = metadata.get("answer")
    model = metadata.get("model", "default")
    
    # PRIVACY REDACTION: Only show content if conversation has feedback
    if not has_feedback:
        query_text = "[REDACTED - PRIVACY]"
        response_text = "[REDACTED - PRIVACY]"

    return ConversationDetail(
        request_id=conv.id,
        tenant_id=conv.tenant_id,
        trace_id=None,
        query_text=query_text or (conv.title if has_feedback else "[REDACTED - PRIVACY]"),
        response_text=response_text or (conv.summary if has_feedback else "[REDACTED - PRIVACY]"),
        model=model,
        provider="openai",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost=0.0,
        feedback=None,
        metadata=metadata if has_feedback else {},  # Redact metadata too
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
    from src.core.generation.domain.memory_models import ConversationSummary

    # Query conversation summary
    query = select(ConversationSummary).where(ConversationSummary.id == request_id)
    result = await session.execute(query)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await session.delete(conv)
    await session.commit()
