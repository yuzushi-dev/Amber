"""
Graph Edit History API
=====================

Endpoints for managing graph edit history (pending changes, undo).
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant_id, get_db_session

router = APIRouter(prefix="/graph/history", tags=["Graph History"])
logger = logging.getLogger(__name__)


# --- Pydantic Models ---


class GraphEditHistoryCreate(BaseModel):
    """Request to create a pending graph edit."""

    action_type: Literal["connect", "merge", "prune", "heal", "delete_edge", "delete_node"]
    payload: dict[str, Any]
    snapshot: dict[str, Any] | None = None
    source_view: str | None = None  # 'global' or 'document:{doc_id}'


class GraphEditHistoryResponse(BaseModel):
    """Response model for a graph edit history entry."""

    id: str
    tenant_id: str
    action_type: str
    status: str
    payload: dict[str, Any]
    snapshot: dict[str, Any] | None = None
    source_view: str | None = None
    created_at: datetime
    applied_at: datetime | None = None


class GraphEditHistoryListResponse(BaseModel):
    """Paginated list of history entries."""

    items: list[GraphEditHistoryResponse]
    total: int
    page: int
    page_size: int


# --- Endpoints ---


@router.get("", response_model=GraphEditHistoryListResponse)
async def list_history(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """List graph edit history (paginated, filterable by status)."""
    offset = (page - 1) * page_size

    # Build query
    base_query = "SELECT * FROM graph_edit_history WHERE tenant_id = :tenant_id"
    count_query = "SELECT COUNT(*) FROM graph_edit_history WHERE tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if status:
        base_query += " AND status = :status"
        count_query += " AND status = :status"
        params["status"] = status

    base_query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = page_size
    params["offset"] = offset

    result = await session.execute(text(base_query), params)
    rows = result.mappings().all()

    count_result = await session.execute(
        text(count_query),
        {"tenant_id": tenant_id, "status": status} if status else {"tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    items = [
        GraphEditHistoryResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            action_type=row["action_type"],
            status=row["status"],
            payload=row["payload"],
            snapshot=row["snapshot"],
            source_view=row["source_view"],
            created_at=row["created_at"],
            applied_at=row["applied_at"],
        )
        for row in rows
    ]

    return GraphEditHistoryListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/pending/count")
async def get_pending_count(
    tenant_id: str = Depends(get_current_tenant_id), session: AsyncSession = Depends(get_db_session)
):
    """Get count of pending edits (for badge display)."""
    result = await session.execute(
        text(
            "SELECT COUNT(*) FROM graph_edit_history WHERE tenant_id = :tenant_id AND status = 'pending'"
        ),
        {"tenant_id": tenant_id},
    )
    count = result.scalar() or 0
    return {"count": count}


@router.post("", response_model=GraphEditHistoryResponse)
async def create_pending_edit(
    request_body: GraphEditHistoryCreate,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new pending graph edit (record without applying)."""
    edit_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # For snapshot, if None we pass 'null' as JSON which will be parsed to SQL NULL by NULLIF
    snapshot_json = json.dumps(request_body.snapshot) if request_body.snapshot else "null"

    await session.execute(
        text("""
            INSERT INTO graph_edit_history (id, tenant_id, action_type, status, payload, snapshot, source_view, created_at)
            VALUES (
                :id, :tenant_id, :action_type, 'pending',
                CAST(:payload AS jsonb),
                NULLIF(CAST(:snapshot AS jsonb), CAST('null' AS jsonb)),
                :source_view, :created_at
            )
        """),
        {
            "id": edit_id,
            "tenant_id": tenant_id,
            "action_type": request_body.action_type,
            "payload": json.dumps(request_body.payload),
            "snapshot": snapshot_json,
            "source_view": request_body.source_view,
            "created_at": now,
        },
    )

    return GraphEditHistoryResponse(
        id=edit_id,
        tenant_id=tenant_id,
        action_type=request_body.action_type,
        status="pending",
        payload=request_body.payload,
        snapshot=request_body.snapshot,
        source_view=request_body.source_view,
        created_at=now,
        applied_at=None,
    )


@router.post("/{edit_id}/apply")
async def apply_pending_edit(
    edit_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Apply a pending edit (execute the action)."""
    # Fetch the pending edit
    result = await session.execute(
        text("SELECT * FROM graph_edit_history WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": edit_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Edit not found")
    if row["status"] != "pending":
        raise HTTPException(
            status_code=400, detail=f"Edit is not pending (status: {row['status']})"
        )

    action_type = row["action_type"]
    payload = row["payload"]

    # Import graph editor functions
    from src.amber_platform.composition_root import platform

    try:
        # Execute the action based on type
        if action_type == "connect":
            # Create edge
            query = """
            MATCH (s:Entity {name: $source, tenant_id: $tenant_id})
            MATCH (t:Entity {name: $target, tenant_id: $tenant_id})
            MERGE (s)-[r:RELATED_TO]->(t)
            SET r.type = $type, r.description = $description, r.weight = 1.0
            RETURN type(r)
            """
            await platform.neo4j_client.execute_write(
                query,
                {
                    "source": payload["source"],
                    "target": payload["target"],
                    "type": payload.get("type", "RELATED_TO"),
                    "description": payload.get("description", ""),
                    "tenant_id": tenant_id,
                },
            )

        elif action_type == "merge":
            success = await platform.neo4j_client.merge_nodes(
                payload["target_id"], payload["source_ids"], tenant_id
            )
            if not success:
                raise Exception("Merge failed")

        elif action_type == "delete_edge":
            query = """
            MATCH (s:Entity {name: $source, tenant_id: $tenant_id})-[r]->(t:Entity {name: $target, tenant_id: $tenant_id})
            DELETE r
            """
            await platform.neo4j_client.execute_write(
                query,
                {"source": payload["source"], "target": payload["target"], "tenant_id": tenant_id},
            )

        elif action_type == "delete_node":
            query = """
            MATCH (n:Entity {name: $node_id, tenant_id: $tenant_id})
            DETACH DELETE n
            """
            await platform.neo4j_client.execute_write(
                query, {"node_id": payload["node_id"], "tenant_id": tenant_id}
            )

        elif action_type == "prune":
            # Prune is typically delete_node or delete_edge depending on payload
            if "node_id" in payload:
                query = """
                MATCH (n:Entity {name: $node_id, tenant_id: $tenant_id})
                DETACH DELETE n
                """
                await platform.neo4j_client.execute_write(
                    query, {"node_id": payload["node_id"], "tenant_id": tenant_id}
                )
            elif "source" in payload and "target" in payload:
                query = """
                MATCH (s:Entity {name: $source, tenant_id: $tenant_id})-[r]->(t:Entity {name: $target, tenant_id: $tenant_id})
                DELETE r
                """
                await platform.neo4j_client.execute_write(
                    query,
                    {
                        "source": payload["source"],
                        "target": payload["target"],
                        "tenant_id": tenant_id,
                    },
                )

        # Update status to applied
        await session.execute(
            text(
                "UPDATE graph_edit_history SET status = 'applied', applied_at = :now WHERE id = :id"
            ),
            {"id": edit_id, "now": datetime.utcnow()},
        )

        return {"status": "applied", "id": edit_id}

    except Exception as e:
        logger.error(f"Failed to apply edit {edit_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{edit_id}")
async def reject_pending_edit(
    edit_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Reject/discard a pending edit."""
    result = await session.execute(
        text("SELECT status FROM graph_edit_history WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": edit_id, "tenant_id": tenant_id},
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Edit not found")
    if row[0] != "pending":
        raise HTTPException(
            status_code=400, detail=f"Only pending edits can be rejected (status: {row[0]})"
        )

    await session.execute(
        text("UPDATE graph_edit_history SET status = 'rejected' WHERE id = :id"), {"id": edit_id}
    )

    return {"status": "rejected", "id": edit_id}


@router.post("/{edit_id}/undo")
async def undo_applied_edit(
    edit_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Undo an applied edit (requires snapshot)."""
    result = await session.execute(
        text("SELECT * FROM graph_edit_history WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": edit_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Edit not found")
    if row["status"] != "applied":
        raise HTTPException(
            status_code=400, detail=f"Only applied edits can be undone (status: {row['status']})"
        )

    action_type = row["action_type"]
    payload = row["payload"]
    snapshot = row["snapshot"]

    from src.amber_platform.composition_root import platform

    try:
        # Reverse the action
        if action_type == "connect":
            # Delete the edge that was created
            query = """
            MATCH (s:Entity {name: $source, tenant_id: $tenant_id})-[r]->(t:Entity {name: $target, tenant_id: $tenant_id})
            DELETE r
            """
            await platform.neo4j_client.execute_write(
                query,
                {"source": payload["source"], "target": payload["target"], "tenant_id": tenant_id},
            )

        elif action_type == "delete_edge":
            # Re-create the edge from snapshot
            if snapshot and "edge" in snapshot:
                edge = snapshot["edge"]
                query = """
                MATCH (s:Entity {name: $source, tenant_id: $tenant_id})
                MATCH (t:Entity {name: $target, tenant_id: $tenant_id})
                MERGE (s)-[r:RELATED_TO]->(t)
                SET r.type = $type, r.description = $description, r.weight = $weight
                """
                await platform.neo4j_client.execute_write(
                    query,
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "type": edge.get("type", "RELATED_TO"),
                        "description": edge.get("description", ""),
                        "weight": edge.get("weight", 1.0),
                        "tenant_id": tenant_id,
                    },
                )
            else:
                raise HTTPException(status_code=400, detail="No snapshot available for undo")

        elif action_type == "delete_node":
            # Re-create node from snapshot
            if snapshot and "node" in snapshot:
                node = snapshot["node"]
                query = """
                CREATE (n:Entity {
                    name: $name,
                    tenant_id: $tenant_id,
                    type: $type,
                    description: $description
                })
                """
                await platform.neo4j_client.execute_write(
                    query,
                    {
                        "name": node["name"],
                        "tenant_id": tenant_id,
                        "type": node.get("type", "Entity"),
                        "description": node.get("description", ""),
                    },
                )
                # Re-create edges from snapshot
                if "edges" in snapshot:
                    for edge in snapshot["edges"]:
                        edge_query = """
                        MATCH (s:Entity {name: $source, tenant_id: $tenant_id})
                        MATCH (t:Entity {name: $target, tenant_id: $tenant_id})
                        MERGE (s)-[r:RELATED_TO]->(t)
                        SET r.type = $type
                        """
                        await platform.neo4j_client.execute_write(
                            edge_query,
                            {
                                "source": edge["source"],
                                "target": edge["target"],
                                "type": edge.get("type", "RELATED_TO"),
                                "tenant_id": tenant_id,
                            },
                        )
            else:
                raise HTTPException(status_code=400, detail="No snapshot available for undo")

        elif action_type == "merge":
            # Merge is very complex to undo - would need full node recreation
            if not snapshot:
                raise HTTPException(
                    status_code=400, detail="Merge undo requires snapshot (not available)"
                )
            # TODO: Implement complex merge undo from snapshot
            raise HTTPException(status_code=501, detail="Merge undo not yet implemented")

        elif action_type == "prune":
            # Undo prune by recreating the deleted node
            if not snapshot:
                raise HTTPException(status_code=400, detail="Prune undo requires snapshot")

            if "node" in snapshot:
                node = snapshot["node"]
                # Recreate the node
                query = """
                CREATE (n:Entity {
                    name: $name,
                    tenant_id: $tenant_id,
                    type: $type,
                    description: $description
                })
                """
                await platform.neo4j_client.execute_write(
                    query,
                    {
                        "name": node.get("label") or node.get("id"),  # Use label or id as name
                        "tenant_id": tenant_id,
                        "type": node.get("type", "Entity"),
                        "description": node.get("description", ""),
                    },
                )

        # Update status
        await session.execute(
            text("UPDATE graph_edit_history SET status = 'undone' WHERE id = :id"), {"id": edit_id}
        )

        return {"status": "undone", "id": edit_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to undo edit {edit_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
