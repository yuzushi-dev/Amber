from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import json
import io

from src.api.deps import get_db_session as get_db
from src.api.schemas.base import ResponseSchema
from src.core.models.feedback import Feedback
from src.shared.context import get_current_tenant

router = APIRouter(prefix="/feedback", tags=["admin-feedback"])

@router.get("/pending", response_model=ResponseSchema[list[dict]])
async def get_pending_feedback(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """List positive feedback waiting for review."""
    tenant_id = get_current_tenant() or "default"
    
    query = (
        select(Feedback)
        .where(
            Feedback.tenant_id == tenant_id,
            Feedback.is_positive == True,
            # We assume None or "NONE" or "PENDING" might be the initial state depending on how we migrated.
            # Ideally we check for golden_status IN ["NONE", "PENDING"]
            Feedback.golden_status.in_(["NONE", "PENDING"])
        )
        .order_by(Feedback.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    return ResponseSchema(data=[
        {
            "id": item.id,
            "request_id": item.request_id,
            "comment": item.comment,
            "created_at": item.created_at,
            "score": item.score
        }
        for item in items
    ])

@router.post("/{feedback_id}/verify", response_model=ResponseSchema[bool])
async def verify_feedback(
    feedback_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Mark feedback as VERIFIED (Golden)."""
    tenant_id = get_current_tenant() or "default"
    
    query = (
        update(Feedback)
        .where(Feedback.id == feedback_id, Feedback.tenant_id == tenant_id)
        .values(golden_status="VERIFIED")
    )
    
    result = await db.execute(query)
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Feedback not found")
        
    return ResponseSchema(data=True, message="Feedback marked as Golden")

@router.post("/{feedback_id}/reject", response_model=ResponseSchema[bool])
async def reject_feedback(
    feedback_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Mark feedback as REJECTED."""
    tenant_id = get_current_tenant() or "default"
    
    query = (
        update(Feedback)
        .where(Feedback.id == feedback_id, Feedback.tenant_id == tenant_id)
        .values(golden_status="REJECTED")
    )
    
    result = await db.execute(query)
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Feedback not found")
        
    return ResponseSchema(data=True, message="Feedback rejected")

@router.get("/export", response_class=StreamingResponse)
async def export_golden_dataset(
    format: str = "jsonl",
    db: AsyncSession = Depends(get_db)
):
    """Export VERIFIED feedback as a JSONL dataset."""
    tenant_id = get_current_tenant() or "default"
    
    # 1. Fetch Verified Feedback
    query = (
        select(Feedback)
        .where(
            Feedback.tenant_id == tenant_id,
            Feedback.golden_status == "VERIFIED"
        )
    )
    result = await db.execute(query)
    feedbacks = result.scalars().all()
    
    # 2. Generator for Streaming
    async def generate():
        for f in feedbacks:
            # Construct the record
            # Ideally we would join with Request/Response logs to get the full text.
            # For now, we rely on metadata having the query/answer if we stored it, 
            # OR we admit this implementation is partial until we link to conversation history.
            # Assuming metadata_json has 'query' and 'answer' from a "Golden" promotion flow or captured at feedback time.
            # If not, we download what we have.
            
            record = {
                "id": f.id,
                "request_id": f.request_id,
                "score": f.score,
                "comment": f.comment,
                "metadata": f.metadata_json
            }
            yield json.dumps(record) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": "attachment; filename=golden_dataset.jsonl"}
    )
