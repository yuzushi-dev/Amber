
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.core.graph.neo4j_client import neo4j_client
from src.shared.context import get_current_tenant as get_tenant_id

router = APIRouter(prefix="/communities", tags=["Communities"])

class CommunityResponse(BaseModel):
    id: str
    title: str
    level: int
    summary: str | None = None
    rating: float = 0
    key_entities: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    status: str
    is_stale: bool
    last_updated_at: str | None = None

@router.get("", response_model=list[CommunityResponse])
async def list_communities(
    level: int | None = Query(None, description="Filter by hierarchy level"),
    tenant_id: str = Depends(get_tenant_id)
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

    results = await neo4j_client.execute_read(query, {"tenant_id": tenant_id, "level": level})
    return [CommunityResponse(**r) for r in results]

@router.get("/{community_id}", response_model=CommunityResponse)
async def get_community(
    community_id: str,
    tenant_id: str = Depends(get_tenant_id)
):
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
    results = await neo4j_client.execute_read(query, {"id": community_id, "tenant_id": tenant_id})
    if not results:
        raise HTTPException(status_code=404, detail="Community not found")

    return CommunityResponse(**results[0])

@router.post("/refresh")
async def trigger_community_refresh(
    tenant_id: str = Depends(get_tenant_id)
):
    """
    Manually trigger community detection and summarization for the tenant.
    """
    from src.workers.tasks import process_communities
    task = process_communities.delay(tenant_id)
    return {"task_id": task.id, "status": "queued"}
