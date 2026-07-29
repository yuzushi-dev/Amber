from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from src.amber_platform.composition_root import platform
from src.api.deps import verify_tenant_admin
from src.shared.context import get_current_tenant as get_tenant_id

_COMMUNITY_REFRESH_COOLDOWN_SECONDS = 300  # 5 min per tenant

router = APIRouter(prefix="/communities", tags=["Communities"])


class CommunityResponse(BaseModel):
    id: str
    title: str
    level: int
    summary: str | None = None
    rating: float | None = None
    key_entities: list[str] | None = None
    findings: list[str] | None = None
    status: str | None = None
    is_stale: bool | None = None
    last_updated_at: str | None = None


@router.get("", response_model=list[CommunityResponse])
async def list_communities(
    level: int | None = Query(None, description="Filter by hierarchy level"),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    List all communities for the current tenant.
    """
    query = """
    MATCH (c:Community {tenant_id: $tenant_id})
    """
    if level is not None:
        query += " WHERE c.level = $level"

    query += """
    RETURN c.id as id, c.title as title, c.level as level, c.summary as summary,
           c.rating as rating, c.key_entities as key_entities, c.findings as findings,
           c.status as status, c.is_stale as is_stale,
           toString(c.last_updated_at) as last_updated_at
    ORDER BY c.level DESC, c.rating DESC
    """

    results = await platform.neo4j_client.execute_read(
        query, {"tenant_id": tenant_id, "level": level}
    )
    return [CommunityResponse(**r) for r in results]


@router.get("/{community_id}", response_model=CommunityResponse)
async def get_community(community_id: str, tenant_id: str = Depends(get_tenant_id)):
    """
    Get detailed information for a specific community.
    """
    query = """
    MATCH (c:Community {id: $id, tenant_id: $tenant_id})
    RETURN c.id as id, c.title as title, c.level as level, c.summary as summary,
           c.rating as rating, c.key_entities as key_entities, c.findings as findings,
           c.status as status, c.is_stale as is_stale,
           toString(c.last_updated_at) as last_updated_at
    """
    results = await platform.neo4j_client.execute_read(
        query, {"id": community_id, "tenant_id": tenant_id}
    )
    if not results:
        raise HTTPException(status_code=404, detail="Community not found")

    return CommunityResponse(**results[0])


@router.post("/refresh", dependencies=[Depends(verify_tenant_admin)])
async def trigger_community_refresh(
    request: Request,
    skip_detection: bool = Query(
        False,
        description="If true, skip community detection (Leiden) and only "
        "run summarization + embedding on existing communities. "
        "Use this to resume summarization without wiping already-summarized communities.",
    ),
    force_full_embedding_resync: bool = Query(
        False,
        description="Re-embed every ready community, including communities whose current "
        "embedding marker already matches. Use only for explicit repair or migration.",
    ),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Manually trigger community detection and summarization for the tenant.
    Throttled to one refresh per tenant per 5 minutes (Redis-backed cooldown).
    """
    # Per-tenant cooldown: reject rapid repeated refresh requests
    try:
        import redis.asyncio as redis_async

        from src.api.config import get_settings
        _settings = get_settings()
        _r = redis_async.from_url(_settings.db.redis_url, decode_responses=True)
        cooldown_key = f"community_refresh_cooldown:{tenant_id}"
        already_queued = await _r.set(
            cooldown_key, "1",
            nx=True,  # only set if not exists
            ex=_COMMUNITY_REFRESH_COOLDOWN_SECONDS,
        )
        await _r.aclose()
        if already_queued is None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Community refresh already queued for this tenant. "                       f"Please wait {_COMMUNITY_REFRESH_COOLDOWN_SECONDS // 60} minutes before retrying.",
            )
    except HTTPException:
        raise
    except Exception as e:
        # Fail closed: if we cannot check cooldown, reject the request
        import logging
        logging.getLogger(__name__).error(f"Community refresh cooldown check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting temporarily unavailable. Please try again later.",
        ) from None

    from src.workers.tasks import process_communities

    task = process_communities.delay(
        tenant_id,
        skip_detection=skip_detection,
        force_full_embedding_resync=force_full_embedding_resync,
    )
    return {
        "task_id": task.id,
        "status": "queued",
        "skip_detection": skip_detection,
        "force_full_embedding_resync": force_full_embedding_resync,
    }
