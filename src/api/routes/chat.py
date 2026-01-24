"""
Chat History Router
==================

User-facing endpoints for managing chat history.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, get_current_tenant_id
from src.core.generation.domain.memory_models import ConversationSummary
from src.api.routes.admin.chat_history import ChatHistoryItem, ChatHistoryResponse, ConversationDetail

router = APIRouter(prefix="/chat", tags=["Chat History"])


@router.get("/history", response_model=ChatHistoryResponse)
async def list_history(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """
    List user's chat history.
    """
    # Determine User ID (match query.py logic)
    # 1. Check header
    # 2. Fallback to 'default_user'
    user_id = request.headers.get("X-User-ID", "default_user") 

    try:
        # Build query
        stmt = select(ConversationSummary).where(
            ConversationSummary.tenant_id == tenant_id,
            ConversationSummary.user_id == user_id
        )

        # Order by most recent
        stmt = stmt.order_by(desc(ConversationSummary.created_at))

        # Count total
        count_stmt = select(func.count(ConversationSummary.id)).where(
            ConversationSummary.tenant_id == tenant_id,
            ConversationSummary.user_id == user_id
        )
        total = await session.scalar(count_stmt) or 0

        # Pagination
        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()

        conversations = []
        for conv in rows:
            metadata = conv.metadata_ or {}
            
            # For the user endpoint, we DO NOT redact content because the user owns it
            query_text = metadata.get("query")
            response_text = metadata.get("answer")
            
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
                model=metadata.get("model", "default"),
                provider="openai", # specific provider info might need better storage if not in metadata
                total_tokens=0, # Metrics not easily joined here without complex query
                cost=0.0,
                has_feedback=False, # We don't check feedback for list view speed
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
        logging.getLogger(__name__).error(f"Failed to list history: {e}")
        return ChatHistoryResponse(
            conversations=[],
            total=0,
            limit=limit,
            offset=offset
        )


@router.get("/history/{conversation_id}", response_model=ConversationDetail)
async def get_history_detail(
    conversation_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get full conversation details.
    """
    user_id = request.headers.get("X-User-ID", "default_user")

    stmt = select(ConversationSummary).where(
        ConversationSummary.id == conversation_id,
        ConversationSummary.tenant_id == tenant_id,
        ConversationSummary.user_id == user_id
    )
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    metadata = conv.metadata_ or {}
    
    return ConversationDetail(
        request_id=conv.id,
        tenant_id=conv.tenant_id,
        trace_id=None,
        query_text=metadata.get("query") or conv.title,
        response_text=metadata.get("answer") or conv.summary,
        model=metadata.get("model", "default"),
        provider="openai",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost=0.0,
        feedback=None,
        metadata=metadata,
        created_at=conv.created_at,
    )


@router.delete("/history/{conversation_id}", status_code=204)
async def delete_history(
    conversation_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a conversation.
    """
    user_id = request.headers.get("X-User-ID", "default_user")

    stmt = select(ConversationSummary).where(
        ConversationSummary.id == conversation_id,
        ConversationSummary.tenant_id == tenant_id,
        ConversationSummary.user_id == user_id
    )
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await session.delete(conv)
    await session.commit()
