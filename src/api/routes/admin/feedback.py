from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, outerjoin, cast, String, func
import json
import io

from src.api.deps import get_db_session as get_db
from src.api.schemas.base import ResponseSchema
from src.core.admin_ops.domain.feedback import Feedback
from src.core.generation.domain.memory_models import ConversationSummary
from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.admin_ops.application.tuning_service import TuningService
from src.core.graph.application.context_writer import context_graph_writer
from src.core.database.session import async_session_maker
from src.shared.context import get_current_tenant
import asyncio

router = APIRouter(prefix="/feedback", tags=["admin-feedback"])

@router.get("/pending", response_model=ResponseSchema[list[dict]])
async def get_pending_feedback(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """List positive feedback waiting for review."""
    
    tenant_id = get_current_tenant() or "default"
    
    # Select Feedback and joined ConversationSummary
    # Join on session_id stored in metadata. We must cast the JSON value to string.
    # Note: metadata_json is generic JSON, so we use func.json_extract_path_text (Postgres) or similar
    # For now, simplistic approach: cast(Feedback.metadata_json['session_id'], String) = ConversationSummary.id 
    # BUT 'astext' is for JSONB. If it's pure JSON, we might need a different approach.
    # safest is likely func.json_extract_path_text(Feedback.metadata_json, 'session_id') if we are on Postgres.
    
    query = (
        select(Feedback, ConversationSummary)
        .outerjoin(
            ConversationSummary, 
            func.json_extract_path_text(Feedback.metadata_json, 'session_id') == ConversationSummary.id
        )
        .where(
            Feedback.tenant_id == tenant_id,
            # Show all feedback types (positive/negative) waiting for review
            Feedback.golden_status.in_(["NONE", "PENDING"])
        )
        .order_by(Feedback.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    
    result = await db.execute(query)
    rows = result.all()
    
    data = []
    for feedback, conversation in rows:
        # Extract query/answer from conversation metadata if available
        # OR from feedback metadata as fallback
        
        query_text = None
        answer_text = None
        
        if conversation and conversation.metadata_:
            query_text = conversation.metadata_.get("query")
            answer_text = conversation.metadata_.get("answer")
            
        # Fallback to feedback metadata if needed
        if not query_text and feedback.metadata_json:
             query_text = feedback.metadata_json.get("query")
             
        if not answer_text and feedback.metadata_json:
             answer_text = feedback.metadata_json.get("answer")
             
        data.append({
            "id": feedback.id,
            "request_id": feedback.request_id,
            "comment": feedback.comment,
            "created_at": feedback.created_at,
            "score": feedback.score,
            "query": query_text,
            "answer": answer_text
        })

    return ResponseSchema(data=data)

@router.post("/{feedback_id}/verify", response_model=ResponseSchema[bool])
async def verify_feedback(
    feedback_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Mark feedback as VERIFIED and compute query embedding for similarity search."""
    
    tenant_id = get_current_tenant() or "default"
    
    # 1. Fetch the feedback and its associated conversation
    stmt = (
        select(Feedback, ConversationSummary)
        .outerjoin(
            ConversationSummary,
            func.json_extract_path_text(Feedback.metadata_json, 'session_id') == ConversationSummary.id
        )
        .where(Feedback.id == feedback_id, Feedback.tenant_id == tenant_id)
    )
    result = await db.execute(stmt)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Feedback not found")
    
    feedback, conversation = row
    
    # 2. Extract query text from conversation or metadata
    query_text = None
    if conversation and conversation.metadata_:
        query_text = conversation.metadata_.get("query")
    if not query_text and feedback.metadata_json:
        query_text = feedback.metadata_json.get("query")
    
    # 3. Compute and store embedding if we have query text
    if query_text:
        try:
            embedding_service = EmbeddingService()
            embedding = await embedding_service.embed_text(query_text)
            if embedding:
                feedback.query_embedding = embedding
        except Exception as e:
            # Don't fail verification if embedding fails
            import logging
            logging.getLogger(__name__).warning(f"Failed to compute embedding for feedback {feedback_id}: {e}")
    
    # 4. Update status and trigger downstream effects
    feedback.golden_status = "VERIFIED"
    # Only use for Q&A injection if positive
    feedback.is_active = feedback.is_positive 
    
    await db.commit()
    
    # 5. Application Effects (Tuning & Graph)
    try:
        # Tuning Analysis
        tuning = TuningService(session_factory=async_session_maker)
        await tuning.analyze_feedback_for_tuning(
            tenant_id=tenant_id,
            request_id=feedback.request_id,
            is_positive=feedback.is_positive,
            comment=feedback.comment,
            selected_snippets=feedback.metadata_json.get("selected_snippets") if feedback.metadata_json else None
        )

        # Graph Reinforcement
        asyncio.create_task(
            context_graph_writer.log_feedback(
                conversation_id=feedback.request_id,
                turn_id=None,
                tenant_id=tenant_id,
                is_positive=feedback.is_positive,
                comment=feedback.comment,
                feedback_id=feedback.id,
            )
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to trigger feedback effects: {e}")
        
    return ResponseSchema(data=True, message="Feedback verified and processed")

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


# =============================================================================
# Q&A Library Endpoints
# =============================================================================

@router.get("/approved", response_model=ResponseSchema[list[dict]])
async def get_approved_feedback(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all VERIFIED Q&A pairs for the Q&A Library."""
    from src.core.generation.domain.memory_models import ConversationSummary
    
    tenant_id = get_current_tenant() or "default"
    
    query = (
        select(Feedback, ConversationSummary)
        .outerjoin(
            ConversationSummary, 
            func.json_extract_path_text(Feedback.metadata_json, 'session_id') == ConversationSummary.id
        )
        .where(
            Feedback.tenant_id == tenant_id,
            Feedback.golden_status == "VERIFIED"
        )
        .order_by(Feedback.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    
    result = await db.execute(query)
    rows = result.all()
    
    data = []
    for feedback, conversation in rows:
        query_text = None
        answer_text = None
        
        if conversation and conversation.metadata_:
            query_text = conversation.metadata_.get("query")
            answer_text = conversation.metadata_.get("answer")
            
        if not query_text and feedback.metadata_json:
            query_text = feedback.metadata_json.get("query")
            
        if not answer_text and feedback.metadata_json:
            answer_text = feedback.metadata_json.get("answer")
              
        data.append({
            "id": feedback.id,
            "request_id": feedback.request_id,
            "comment": feedback.comment,
            "created_at": feedback.created_at,
            "score": feedback.score,
            "is_active": feedback.is_active,
            "query": query_text,
            "answer": answer_text
        })

    return ResponseSchema(data=data)


@router.put("/{feedback_id}/toggle-active", response_model=ResponseSchema[bool])
async def toggle_feedback_active(
    feedback_id: str,
    is_active: bool,
    db: AsyncSession = Depends(get_db)
):
    """Toggle whether a verified Q&A is active (used for injection)."""
    tenant_id = get_current_tenant() or "default"
    
    query = (
        update(Feedback)
        .where(
            Feedback.id == feedback_id,
            Feedback.tenant_id == tenant_id,
            Feedback.golden_status == "VERIFIED"
        )
        .values(is_active=is_active)
    )
    
    result = await db.execute(query)
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Verified feedback not found")
        
    return ResponseSchema(data=True, message=f"Feedback {'activated' if is_active else 'deactivated'}")


@router.delete("/{feedback_id}", response_model=ResponseSchema[bool])
async def delete_feedback(
    feedback_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a feedback item from the library."""
    from sqlalchemy import delete as sql_delete
    
    tenant_id = get_current_tenant() or "default"
    
    query = (
        sql_delete(Feedback)
        .where(
            Feedback.id == feedback_id,
            Feedback.tenant_id == tenant_id
        )
    )
    
    result = await db.execute(query)
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Feedback not found")
        
    return ResponseSchema(data=True, message="Feedback deleted")
