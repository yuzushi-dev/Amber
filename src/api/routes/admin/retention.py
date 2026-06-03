"""
Data Retention API
==================

Admin endpoints for managing user memory and conversation summaries.
Allows for listing and deletion of stored data (GDPR/Privacy control).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_tenant_admin
from src.core.generation.application.memory.manager import memory_manager
from src.core.generation.domain.memory_models import ConversationSummary, UserFact

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/retention", tags=["admin-retention"], dependencies=[Depends(verify_tenant_admin)])


# Schemas
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


def _resolve_tenant_id(request: Request, tenant_id_param: str | None) -> str:
    """
    Resolve the effective tenant_id for a retention endpoint.

    - Super-admin: may pass an explicit ?tenant_id= query param; falls back to
      their own tenant if omitted.
    - Tenant-admin: always uses their own tenant; any explicit param is ignored.
    """
    is_super_admin = getattr(request.state, "is_super_admin", False)
    caller_tenant = str(getattr(request.state, "tenant_id", ""))

    if is_super_admin:
        return tenant_id_param if tenant_id_param else caller_tenant
    return caller_tenant


@router.get("/facts", response_model=PaginationResponse)
async def list_facts(
    request: Request,
    tenant_id: str | None = Query(None, description="Target tenant (super-admin only)"),
    user_id: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    """List stored user facts with pagination and filtering."""
    effective_tenant = _resolve_tenant_id(request, tenant_id)

    # Build query
    stmt = select(UserFact).where(UserFact.tenant_id == effective_tenant)
    count_stmt = (
        select(func.count()).select_from(UserFact).where(UserFact.tenant_id == effective_tenant)
    )

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
            metadata=f.metadata_,
        )
        for f in facts
    ]

    return PaginationResponse(total=total, page=page, size=size, data=data)


@router.delete("/facts/{fact_id}")
async def delete_fact(
    fact_id: str,
    request: Request,
    tenant_id: str | None = Query(None, description="Target tenant (super-admin only)"),
):
    """Delete a specific user fact."""
    effective_tenant = _resolve_tenant_id(request, tenant_id)
    success = await memory_manager.delete_user_fact(effective_tenant, fact_id)
    if not success:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "success", "message": "Fact deleted"}


@router.get("/summaries", response_model=PaginationResponse)
async def list_summaries(
    request: Request,
    tenant_id: str | None = Query(None, description="Target tenant (super-admin only)"),
    user_id: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    """List conversation summaries with pagination."""
    effective_tenant = _resolve_tenant_id(request, tenant_id)

    # Build query
    stmt = select(ConversationSummary).where(ConversationSummary.tenant_id == effective_tenant)
    count_stmt = (
        select(func.count())
        .select_from(ConversationSummary)
        .where(ConversationSummary.tenant_id == effective_tenant)
    )

    if user_id:
        stmt = stmt.where(ConversationSummary.user_id == user_id)
        count_stmt = count_stmt.where(ConversationSummary.user_id == user_id)

    # Count total
    total = (await session.execute(count_stmt)).scalar() or 0

    # Fetch data
    stmt = (
        stmt.order_by(desc(ConversationSummary.created_at))
        .offset((page - 1) * size)
        .limit(size)
    )
    result = await session.execute(stmt)
    summaries = result.scalars().all()

    data = [
        SummaryResponse(
            id=s.id,
            user_id=s.user_id,
            title=s.title,
            summary=s.summary,
            created_at=s.created_at.isoformat(),
            metadata=s.metadata_,
        )
        for s in summaries
    ]

    return PaginationResponse(total=total, page=page, size=size, data=data)


@router.delete("/summaries/{summary_id}")
async def delete_summary(
    summary_id: str,
    request: Request,
    tenant_id: str | None = Query(None, description="Target tenant (super-admin only)"),
):
    """Delete a conversation summary."""
    effective_tenant = _resolve_tenant_id(request, tenant_id)
    success = await memory_manager.delete_conversation_summary(effective_tenant, summary_id)
    if not success:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"status": "success", "message": "Summary deleted"}
