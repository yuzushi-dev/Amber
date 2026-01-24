"""
Curation Queue API
==================

Admin endpoints for managing analyst feedback flags and data quality issues.

Stage 10.3 - Curation Queue (SME Loop) Backend
"""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, func
from sqlalchemy.future import select

from src.core.database.session import async_session_maker
from src.core.admin_ops.domain.flag import Flag, FlagStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/curation", tags=["admin-curation"])


# =============================================================================
# Schemas
# =============================================================================

class FlagContext(BaseModel):
    """Context information for a flag."""
    query_text: str | None = None
    chunk_text: str | None = None
    chunk_id: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    relationship_id: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    request_id: str | None = None
    retrieval_trace: dict | None = None


class FlagSummary(BaseModel):
    """Summary of a flag for list views."""
    id: str
    tenant_id: str
    type: str
    status: str
    reported_by: str
    target_type: str
    target_id: str
    comment: str | None = None
    snippet_preview: str | None = Field(None, max_length=200)
    created_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None


class FlagDetail(FlagSummary):
    """Detailed flag information including context."""
    context: FlagContext
    resolution_notes: str | None = None
    merge_target_id: str | None = None


class FlagListResponse(BaseModel):
    """List of flags response."""
    flags: list[FlagSummary]
    total: int
    pending_count: int
    resolved_count: int


class FlagResolution(BaseModel):
    """Flag resolution request."""
    action: str = Field(..., description="Resolution action: accept, reject, merge")
    notes: str | None = Field(None, description="Resolution notes")
    merge_target_id: str | None = Field(None, description="Target entity ID for merge action")


class FlagCreateRequest(BaseModel):
    """Create flag request."""
    tenant_id: str
    flag_type: str
    target_type: str
    target_id: str
    reported_by: str = "analyst"
    comment: str | None = None
    context: FlagContext | None = None


class CurationStats(BaseModel):
    """Curation queue statistics."""
    total_flags: int
    pending_count: int
    accepted_count: int
    rejected_count: int
    merged_count: int
    avg_resolution_time_hours: float | None = None
    flags_by_type: dict


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/flags", response_model=FlagListResponse)
async def list_flags(
    status: str | None = Query(None, description="Filter by status"),
    flag_type: str | None = Query(None, description="Filter by type"),
    tenant_id: str | None = Query(None, description="Filter by tenant"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    List flags in the curation queue.

    Returns paginated list of analyst-reported issues with filtering options.
    """
    try:
        async with async_session_maker() as session:
            # Build query
            query = select(Flag)

            if status:
                query = query.where(Flag.status == status)
            if flag_type:
                query = query.where(Flag.type == flag_type)
            if tenant_id:
                query = query.where(Flag.tenant_id == tenant_id)

            # Get total count
            count_query = select(func.count()).select_from(query.subquery())
            total_result = await session.execute(count_query)
            total = total_result.scalar() or 0

            # Apply pagination and ordering
            query = query.order_by(Flag.created_at.desc()).offset(offset).limit(limit)

            # Execute
            result = await session.execute(query)
            flags = result.scalars().all()

            # Get counts
            pending_query = select(func.count()).select_from(Flag).where(Flag.status == FlagStatus.PENDING.value)
            pending_result = await session.execute(pending_query)
            pending_count = pending_result.scalar() or 0

            resolved_count = total - pending_count

            # Convert to summaries
            flag_summaries = []
            for flag in flags:
                context = flag.context or {}
                snippet = context.get("chunk_text", "")[:200] if context else ""

                flag_summaries.append(FlagSummary(
                    id=flag.id,
                    tenant_id=flag.tenant_id,
                    type=flag.type.value if hasattr(flag.type, 'value') else flag.type,
                    status=flag.status.value if hasattr(flag.status, 'value') else flag.status,
                    reported_by=flag.reported_by,
                    target_type=flag.target_type,
                    target_id=flag.target_id,
                    comment=flag.comment,
                    snippet_preview=snippet,
                    created_at=flag.created_at.isoformat() if flag.created_at else "",
                    resolved_at=flag.resolved_at,
                    resolved_by=flag.resolved_by,
                ))

            return FlagListResponse(
                flags=flag_summaries,
                total=total,
                pending_count=pending_count,
                resolved_count=resolved_count,
            )

    except Exception as e:
        logger.error(f"Failed to list flags: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list flags: {str(e)}") from e


@router.get("/flags/{flag_id}", response_model=FlagDetail)
async def get_flag(flag_id: str):
    """
    Get detailed information about a specific flag.

    Returns full context including source chunk, query, and retrieval trace.
    """
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(Flag).where(Flag.id == flag_id))
            flag = result.scalar_one_or_none()

            if not flag:
                raise HTTPException(status_code=404, detail=f"Flag {flag_id} not found")

            context = flag.context or {}
            snippet = context.get("chunk_text", "")[:200] if context else ""

            return FlagDetail(
                id=flag.id,
                tenant_id=flag.tenant_id,
                type=flag.type.value if hasattr(flag.type, 'value') else flag.type,
                status=flag.status.value if hasattr(flag.status, 'value') else flag.status,
                reported_by=flag.reported_by,
                target_type=flag.target_type,
                target_id=flag.target_id,
                comment=flag.comment,
                snippet_preview=snippet,
                created_at=flag.created_at.isoformat() if flag.created_at else "",
                resolved_at=flag.resolved_at,
                resolved_by=flag.resolved_by,
                context=FlagContext(**context),
                resolution_notes=flag.resolution_notes,
                merge_target_id=flag.merge_target_id,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get flag {flag_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get flag: {str(e)}") from e


@router.put("/flags/{flag_id}", response_model=FlagDetail)
async def resolve_flag(flag_id: str, resolution: FlagResolution):
    """
    Resolve a flag with an action.

    Actions:
    - `accept`: Accept the flag and apply correction
    - `reject`: Reject the flag (false positive)
    - `merge`: Merge entities (requires merge_target_id)
    """
    try:
        # Validate action
        valid_actions = ["accept", "reject", "merge"]
        if resolution.action not in valid_actions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action. Must be one of: {valid_actions}"
            )

        # Validate merge requires target
        if resolution.action == "merge" and not resolution.merge_target_id:
            raise HTTPException(
                status_code=400,
                detail="merge_target_id required for merge action"
            )

        async with async_session_maker() as session:
            result = await session.execute(select(Flag).where(Flag.id == flag_id))
            flag = result.scalar_one_or_none()

            if not flag:
                raise HTTPException(status_code=404, detail=f"Flag {flag_id} not found")

            # Update flag
            now = datetime.now(UTC)
            if resolution.action == "merge":
                flag.status = FlagStatus.MERGED
                flag.merge_target_id = resolution.merge_target_id
            elif resolution.action == "accept":
                flag.status = FlagStatus.ACCEPTED
            else:  # reject
                flag.status = FlagStatus.REJECTED

            flag.resolved_at = now.isoformat()
            flag.resolved_by = "admin"  # TODO: Get from auth context
            flag.resolution_notes = resolution.notes

            session.add(flag)
            await session.commit()
            await session.refresh(flag)

            logger.info(f"Resolved flag {flag_id} with action {resolution.action}")

        return await get_flag(flag_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resolve flag {flag_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resolve flag: {str(e)}") from e


@router.post("/flags")
async def create_flag(request: FlagCreateRequest):
    """
    Create a new flag (for testing or manual flagging).

    In production, flags are typically created from the Analyst UI's feedback buttons.
    """
    try:
        async with async_session_maker() as session:
            flag = Flag(
                id=str(uuid4()),
                tenant_id=request.tenant_id,
                type=request.flag_type,
                status=FlagStatus.PENDING,
                target_type=request.target_type,
                target_id=request.target_id,
                reported_by=request.reported_by,
                comment=request.comment,
                context=request.context.model_dump() if request.context else {},
            )

            session.add(flag)
            await session.commit()

            logger.info(f"Created flag {flag.id} of type {request.flag_type}")

            return {"id": flag.id, "status": "created"}

    except Exception as e:
        logger.error(f"Failed to create flag: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create flag: {str(e)}") from e


@router.get("/stats", response_model=CurationStats)
async def get_curation_stats():
    """
    Get curation queue statistics with optimized queries and caching.

    Returns counts by status and type, plus resolution time metrics.
    """
    try:
        from src.core.cache.decorators import get_from_cache, set_cache

        # Check cache first
        cache_key = "admin:stats:curation"
        cached = await get_from_cache(cache_key)
        if cached:
            return CurationStats(**cached)

        async with async_session_maker() as session:
            # OPTIMIZED: Single query for counts by status using GROUP BY
            status_query = select(
                Flag.status,
                func.count().label('count')
            ).group_by(Flag.status)

            status_result = await session.execute(status_query)
            status_counts = {row.status: row.count for row in status_result}

            # Total is sum of all status counts
            total = sum(status_counts.values())

            # Extract individual counts (default to 0 if status doesn't exist)
            pending = status_counts.get(FlagStatus.PENDING.value, 0)
            accepted = status_counts.get(FlagStatus.ACCEPTED.value, 0)
            rejected = status_counts.get(FlagStatus.REJECTED.value, 0)
            merged = status_counts.get(FlagStatus.MERGED.value, 0)

            # Counts by type (already uses GROUP BY - keep as is)
            type_result = await session.execute(
                select(Flag.type, func.count()).group_by(Flag.type)
            )
            by_type = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in type_result}

            # OPTIMIZED: Calculate average resolution time in SQL
            # Extract EPOCH from timestamp difference for resolution time calculation
            resolution_query = select(
                func.avg(
                    func.extract('epoch', func.cast(Flag.resolved_at, DateTime) - Flag.created_at) / 3600
                ).label('avg_hours')
            ).where(Flag.resolved_at.isnot(None))

            resolution_result = await session.execute(resolution_query)
            avg_time = resolution_result.scalar()

            stats = CurationStats(
                total_flags=total,
                pending_count=pending,
                accepted_count=accepted,
                rejected_count=rejected,
                merged_count=merged,
                avg_resolution_time_hours=round(avg_time, 2) if avg_time else None,
                flags_by_type=by_type,
            )

            # Cache for 30 seconds
            await set_cache(cache_key, stats.dict(), ttl=30)
            return stats

    except Exception as e:
        logger.error(f"Failed to get curation stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}") from e

