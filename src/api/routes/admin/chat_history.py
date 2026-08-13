"""
Chat History Admin Router
==========================

Endpoints for viewing chat conversation history.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, verify_super_admin, verify_tenant_admin
from src.core.admin_ops.domain.feedback import Feedback

# Content shown only when the conversation has user feedback attached.
REDACTED = "[REDACTED - no user feedback]"

router = APIRouter(
    prefix="/chat",
    tags=["Admin - Chat History"],
    dependencies=[Depends(verify_super_admin)],
)


# =============================================================================
# Response Models
# =============================================================================


class ChatHistoryItem(BaseModel):
    """Single chat history entry."""

    request_id: str
    tenant_id: str
    group_name: str | None = None
    query_text: str | None = None
    response_preview: str | None = None
    model: str
    provider: str
    total_tokens: int
    cost: float
    has_feedback: bool
    feedback_score: float | None = None
    feedback_positive: bool | None = None  # None = no feedback; True/False = thumbs up/down
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    sources: list | None = None
    metadata: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
        is_super = getattr(request.state, "is_super_admin", False)
        if not is_super:
            tenant_id = str(getattr(request.state, "tenant_id", ""))

        # Build query for conversation summaries
        query = select(ConversationSummary)

        # Filter by tenant if specified
        if tenant_id:
            query = query.where(ConversationSummary.tenant_id == tenant_id)

        # Order by most recent first
        query = query.order_by(desc(ConversationSummary.created_at))

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
        feedback_query = (
            select(Feedback.request_id, Feedback.is_positive)
            .join(
                ConversationSummary,
                and_(
                    Feedback.request_id == ConversationSummary.id,
                    Feedback.tenant_id == ConversationSummary.tenant_id,
                ),
            )
            .where(Feedback.request_id.in_(conv_ids))
            .order_by(Feedback.created_at.desc())
        )
        feedback_result = await session.execute(feedback_query)
        # Latest feedback per conversation wins (rows ordered desc; first seen kept).
        feedback_positive_by_conv: dict[str, bool | None] = {}
        for req_id, is_positive in feedback_result.fetchall():
            feedback_positive_by_conv.setdefault(req_id, is_positive)
        conversations_with_feedback = set(feedback_positive_by_conv.keys())

        # Build api_key_id → group_name lookup. Keyed on the immutable API
        # key id, not its name (issue #72): `conv.user_id` mirrors the
        # caller-controlled X-User-ID header, which can be set to any
        # string including an unrelated key's *name* — and key names are not
        # even unique (ix_api_keys_name has unique=False), so a name-keyed
        # lookup could attribute a conversation to the wrong group on a
        # collision. `conv.api_key_id` is populated at write time from the
        # authenticated key and is NULL on rows written before that column
        # existed, which correctly yields "no group" below rather than a
        # guess.
        from sqlalchemy import text as sa_text

        grp_result = await session.execute(
            sa_text("""
            SELECT ak.id AS key_id, g.name AS group_name
            FROM api_keys ak
            JOIN group_members gm ON gm.api_key_id = ak.id
            JOIN groups g ON g.id = gm.group_id
            WHERE g.is_active = true
        """)
        )
        key_to_group: dict[str, str] = {r.key_id: r.group_name for r in grp_result.fetchall()}

        for conv in rows:
            metadata = conv.metadata_ or {}
            model = metadata.get("model", "default")
            has_feedback = conv.id in conversations_with_feedback
            feedback_positive = feedback_positive_by_conv.get(conv.id)
            group_name = key_to_group.get(conv.api_key_id)

            conv_metrics = metrics_by_conv.get(conv.id, {})
            if conv_metrics.get("model"):
                model = conv_metrics["model"]
            provider = conv_metrics.get("provider", "openai")

            history: list[dict] = metadata.get("history") or []

            from src.api.config import settings as _settings

            redact_enabled = _settings.chat_redact_without_feedback

            if len(history) <= 1:
                # Single-turn: original behaviour
                if has_feedback or not redact_enabled:
                    query_text = metadata.get("query")
                    response_text = metadata.get("answer")
                    response_preview = None
                    if response_text:
                        response_preview = (
                            response_text[:100] + "..."
                            if len(response_text) > 100
                            else response_text
                        )
                    elif conv.summary:
                        response_preview = conv.summary[:100]
                    display_query = query_text or conv.title
                else:
                    display_query = REDACTED
                    response_preview = REDACTED

                conversations.append(
                    ChatHistoryItem(
                        request_id=conv.id,
                        tenant_id=conv.tenant_id,
                        group_name=group_name,
                        query_text=display_query,
                        response_preview=response_preview,
                        model=model,
                        provider=provider,
                        total_tokens=conv_metrics.get("total_tokens", 0),
                        cost=conv_metrics.get("cost", 0.0),
                        has_feedback=has_feedback,
                        feedback_score=None,
                        feedback_positive=feedback_positive,
                        created_at=conv.created_at,
                    )
                )
            else:
                # Multi-turn: one row per turn; tokens/cost on first turn only
                for idx, turn in enumerate(history):
                    turn_ts_str = turn.get("timestamp")
                    try:
                        turn_ts = (
                            datetime.fromisoformat(turn_ts_str) if turn_ts_str else conv.created_at
                        )
                    except Exception:
                        turn_ts = conv.created_at

                    if has_feedback or not redact_enabled:
                        turn_query = turn.get("query", "")
                        turn_answer = turn.get("answer", "")
                        display_turn_query = turn_query or conv.title
                        response_preview = (
                            (turn_answer[:100] + "...")
                            if len(turn_answer) > 100
                            else turn_answer or None
                        )
                    else:
                        display_turn_query = REDACTED
                        response_preview = REDACTED

                    conversations.append(
                        ChatHistoryItem(
                            request_id=f"{conv.id}:{idx}",
                            tenant_id=conv.tenant_id,
                            group_name=group_name,
                            query_text=display_turn_query,
                            response_preview=response_preview,
                            model=model,
                            provider=provider,
                            total_tokens=conv_metrics.get("total_tokens", 0) if idx == 0 else 0,
                            cost=conv_metrics.get("cost", 0.0) if idx == 0 else 0.0,
                            has_feedback=has_feedback and idx == 0,
                            feedback_score=None,
                            feedback_positive=feedback_positive if idx == 0 else None,
                            created_at=turn_ts,
                        )
                    )

        # Sort by created_at desc after flattening multi-turn conversations
        conversations.sort(key=lambda x: x.created_at, reverse=True)

        return ChatHistoryResponse(
            conversations=conversations,
            total=len(conversations),
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        import logging
        import traceback

        logging.getLogger(__name__).error(
            f"Chat history query failed: {e}\n{traceback.format_exc()}"
        )
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
    _: None = Depends(verify_tenant_admin),
):
    """
    Get full details for a specific conversation.
    """
    from src.core.generation.domain.memory_models import ConversationSummary

    is_super = getattr(request.state, "is_super_admin", False)
    if not is_super:
        request_tenant = str(getattr(request.state, "tenant_id", ""))

    # Multi-turn rows use "{conv_id}:{turn_idx}" — strip the suffix
    conv_id = request_id.split(":")[0]

    # Query conversation summary
    query = select(ConversationSummary).where(ConversationSummary.id == conv_id)
    if not is_super:
        query = query.where(ConversationSummary.tenant_id == request_tenant)

    result = await session.execute(query)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if conversation has feedback
    feedback_query = (
        select(Feedback)
        .where(
            Feedback.request_id == conv_id,
            Feedback.tenant_id == conv.tenant_id,
        )
        .limit(1)
    )
    feedback_result = await session.execute(feedback_query)
    feedback_row = feedback_result.scalar_one_or_none()
    has_feedback = feedback_row is not None
    feedback_payload = (
        {
            "is_positive": feedback_row.is_positive,
            "score": feedback_row.score,
            "comment": feedback_row.comment,
            "correction": feedback_row.correction,
            "created_at": feedback_row.created_at.isoformat() if feedback_row.created_at else None,
        }
        if has_feedback
        else None
    )

    # Extract details
    from src.api.config import settings as _settings

    redact_enabled = _settings.chat_redact_without_feedback

    metadata = conv.metadata_ or {}
    if has_feedback or not redact_enabled:
        query_text = metadata.get("query")
        response_text = metadata.get("answer")
    else:
        query_text = REDACTED
        response_text = REDACTED
    model = metadata.get("model", "default")
    provider = "openai"

    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cost = 0.0

    # Fetch metrics
    from src.api.config import settings
    from src.core.admin_ops.application.metrics.collector import MetricsCollector

    collector = MetricsCollector(redis_url=settings.db.redis_url)
    all_metrics = await collector.get_recent(tenant_id=conv.tenant_id, limit=2000)
    for m in all_metrics:
        if m.conversation_id == request_id:
            it = getattr(m, "input_tokens", 0)
            ot = getattr(m, "output_tokens", 0)
            input_tokens += it
            output_tokens += ot
            total_tokens += m.tokens_used if m.tokens_used > 0 else (it + ot)
            cost += m.cost_estimate
            if m.model:
                model = m.model
            if hasattr(m, "provider"):
                provider = getattr(m, "provider", provider)

    # Build a safe copy of metadata: redact raw content when no feedback and redaction enabled.
    safe_metadata = dict(metadata)
    if not has_feedback and redact_enabled:
        if "query" in safe_metadata:
            safe_metadata["query"] = REDACTED
        if "answer" in safe_metadata:
            safe_metadata["answer"] = REDACTED

    return ConversationDetail(
        request_id=conv.id,
        tenant_id=conv.tenant_id,
        trace_id=None,
        query_text=(query_text or conv.title) if (has_feedback or not redact_enabled) else REDACTED,
        response_text=(response_text or conv.summary)
        if (has_feedback or not redact_enabled)
        else REDACTED,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost=cost,
        feedback=feedback_payload,
        sources=metadata.get("sources"),
        metadata=safe_metadata,
        created_at=conv.created_at,
    )


@router.delete("/history/{request_id}", status_code=204)
async def delete_conversation(
    request_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a specific conversation.
    """
    from src.core.generation.domain.memory_models import ConversationSummary

    is_super = getattr(request.state, "is_super_admin", False)
    if not is_super:
        request_tenant = str(getattr(request.state, "tenant_id", ""))

    conv_id = request_id.split(":")[0]

    query = select(ConversationSummary).where(ConversationSummary.id == conv_id)
    if not is_super:
        query = query.where(ConversationSummary.tenant_id == request_tenant)

    result = await session.execute(query)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await session.delete(conv)
    await session.commit()
