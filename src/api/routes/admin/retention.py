"""
Data Retention API
==================

Admin endpoints for managing user memory and conversation summaries.
Allows for listing and deletion of stored data (GDPR/Privacy control).
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.core.generation.domain.memory_models import UserFact, ConversationSummary
from src.core.generation.application.memory.manager import memory_manager
from src.core.database import get_session_maker
from sqlalchemy import select, desc, func
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retention", tags=["admin-retention"])

#Schemas
class FactResponse(BaseModel):
    id: str
    user_id: str
    content: str
    importance: float
    created_at: str
    metadata: dict[str, Any]

class SummaryResponse(BaseModel):
    id: str
    user_id: str
    title: str
    summary: str
    created_at: str
    metadata: dict[str, Any]

class PaginationResponse(BaseModel):
    total: int
    page: int
    size: int
    data: list[Any]

@router.get("/facts", response_model=PaginationResponse)
async def list_facts(
    tenant_id: str = "default", # In real admin, this might come from admin context
    user_id: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100)
):
    """List stored user facts with pagination and filtering."""
    async with get_session_maker()() as session:
        # Build query
        stmt = select(UserFact).where(UserFact.tenant_id == tenant_id)
        count_stmt = select(func.count()).select_from(UserFact).where(UserFact.tenant_id == tenant_id)
        
        if user_id:
            stmt = stmt.where(UserFact.user_id == user_id)
            count_stmt = count_stmt.where(UserFact.user_id == user_id)
            
        # Count total
        total = (await session.execute(count_stmt)).scalar() or 0
        
        # Fetch data
        stmt = stmt.order_by(desc(UserFact.created_at)).offset((page - 1) * size).limit(size)
        result = await session.execute(stmt)
        facts = result.scalars().all()
        
        data = [
            FactResponse(
                id=f.id,
                user_id=f.user_id,
                content=f.content,
                importance=f.importance,
                created_at=f.created_at.isoformat(),
                metadata=f.metadata_
            ) for f in facts
        ]
        
        return PaginationResponse(total=total, page=page, size=size, data=data)

@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, tenant_id: str = "default"):
    """Delete a specific user fact."""
    success = await memory_manager.delete_user_fact(tenant_id, fact_id)
    if not success:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "success", "message": "Fact deleted"}

@router.get("/summaries", response_model=PaginationResponse)
async def list_summaries(
    tenant_id: str = "default",
    user_id: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100)
):
    """List conversation summaries with pagination."""
    async with get_session_maker()() as session:
        # Build query
        stmt = select(ConversationSummary).where(ConversationSummary.tenant_id == tenant_id)
        count_stmt = select(func.count()).select_from(ConversationSummary).where(ConversationSummary.tenant_id == tenant_id)
        
        if user_id:
            stmt = stmt.where(ConversationSummary.user_id == user_id)
            count_stmt = count_stmt.where(ConversationSummary.user_id == user_id)
            
        # Count total
        total = (await session.execute(count_stmt)).scalar() or 0
        
        # Fetch data
        stmt = stmt.order_by(desc(ConversationSummary.created_at)).offset((page - 1) * size).limit(size)
        result = await session.execute(stmt)
        summaries = result.scalars().all()
        
        data = [
            SummaryResponse(
                id=s.id,
                user_id=s.user_id,
                title=s.title,
                summary=s.summary,
                created_at=s.created_at.isoformat(),
                metadata=s.metadata_
            ) for s in summaries
        ]
        
        return PaginationResponse(total=total, page=page, size=size, data=data)

@router.delete("/summaries/{summary_id}")
async def delete_summary(summary_id: str, tenant_id: str = "default"):
    """Delete a conversation summary."""
    success = await memory_manager.delete_conversation_summary(tenant_id, summary_id)
    if not success:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"status": "success", "message": "Summary deleted"}
