"""
Context Graph Admin API
=======================

Endpoints for querying and managing the Context Graph (decision traces).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import verify_admin
from src.amber_platform.composition_root import platform
from src.core.graph.domain.schema import NodeLabel, RelationshipType

router = APIRouter(prefix="/context-graph", tags=["admin", "context-graph"])
logger = logging.getLogger(__name__)


# =============================================================================
# Schemas
# =============================================================================

class FeedbackGraphItem(BaseModel):
    """Feedback node from Context Graph with related turn/chunk info."""
    feedback_id: str
    is_positive: bool
    comment: str | None
    created_at: str
    turn_query: str | None
    turn_answer: str | None
    turn_id: str | None
    chunks_affected: list[dict[str, Any]]


class ContextGraphStats(BaseModel):
    """Statistics about the Context Graph."""
    total_conversations: int
    total_turns: int
    total_feedback: int
    positive_feedback: int
    negative_feedback: int


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/stats", response_model=ContextGraphStats)
async def get_context_graph_stats(
    _admin: Any = Depends(verify_admin),
):
    """Get overall statistics of the Context Graph."""
    try:
        await platform.neo4j_client.connect()
        
        # Count conversations
        conv_result = await platform.neo4j_client.execute_read(
            f"MATCH (c:{NodeLabel.Conversation.value}) RETURN count(c) as count"
        )
        conv_count = conv_result[0]["count"] if conv_result else 0
        
        # Count turns
        turn_result = await platform.neo4j_client.execute_read(
            f"MATCH (t:{NodeLabel.Turn.value}) RETURN count(t) as count"
        )
        turn_count = turn_result[0]["count"] if turn_result else 0
        
        # Count feedback
        fb_result = await platform.neo4j_client.execute_read(
            f"""
            MATCH (f:{NodeLabel.UserFeedback.value})
            RETURN 
                count(f) as total,
                sum(CASE WHEN f.is_positive THEN 1 ELSE 0 END) as positive,
                sum(CASE WHEN NOT f.is_positive THEN 1 ELSE 0 END) as negative
            """
        )
        fb_data = fb_result[0] if fb_result else {"total": 0, "positive": 0, "negative": 0}
        
        return ContextGraphStats(
            total_conversations=conv_count,
            total_turns=turn_count,
            total_feedback=fb_data.get("total", 0) or 0,
            positive_feedback=fb_data.get("positive", 0) or 0,
            negative_feedback=fb_data.get("negative", 0) or 0,
        )
        
    except Exception as e:
        logger.error(f"Failed to get context graph stats: {e}")
        return ContextGraphStats(
            total_conversations=0,
            total_turns=0,
            total_feedback=0,
            positive_feedback=0,
            negative_feedback=0,
        )


@router.get("/feedback", response_model=list[FeedbackGraphItem])
async def list_graph_feedback(
    limit: int = 50,
    _admin: Any = Depends(verify_admin),
):
    """List feedback from the Context Graph with related turn and chunk info."""
    try:
        await platform.neo4j_client.connect()
        
        result = await platform.neo4j_client.execute_read(
            f"""
            MATCH (f:{NodeLabel.UserFeedback.value})
            OPTIONAL MATCH (f)-[:{RelationshipType.RATES.value}]->(t:{NodeLabel.Turn.value})
            OPTIONAL MATCH (t)-[r:{RelationshipType.RETRIEVED.value}]->(c:{NodeLabel.Chunk.value})
            WITH f, t, collect({{chunk_id: c.id, score: r.score}}) as chunks
            RETURN 
                f.id as feedback_id,
                f.is_positive as is_positive,
                f.comment as comment,
                f.created_at as created_at,
                t.query as turn_query,
                t.answer as turn_answer,
                t.id as turn_id,
                chunks
            ORDER BY f.created_at DESC
            LIMIT $limit
            """,
            parameters={"limit": limit}
        )
        
        items = []
        for record in result:
            # Filter out null chunks
            chunks = [c for c in record.get("chunks", []) if c.get("chunk_id")]
            items.append(FeedbackGraphItem(
                feedback_id=record["feedback_id"],
                is_positive=record["is_positive"],
                comment=record.get("comment"),
                created_at=record.get("created_at", ""),
                turn_query=record.get("turn_query"),
                turn_answer=record.get("turn_answer"),
                turn_id=record.get("turn_id"),
                chunks_affected=chunks,
            ))
        
        return items
        
    except Exception as e:
        logger.error(f"Failed to list graph feedback: {e}")
        return []


@router.delete("/feedback/{feedback_id}")
async def delete_graph_feedback(
    feedback_id: str,
    _admin: Any = Depends(verify_admin),
):
    """Remove a feedback node and its relationships from the Context Graph."""
    try:
        await platform.neo4j_client.connect()
        
        # Delete feedback node and its relationships
        await platform.neo4j_client.execute_write(
            f"""
            MATCH (f:{NodeLabel.UserFeedback.value} {{id: $feedback_id}})
            DETACH DELETE f
            """,
            parameters={"feedback_id": feedback_id}
        )
        
        logger.info(f"Deleted feedback {feedback_id} from Context Graph")
        return {"message": "Feedback removed from Context Graph", "deleted": feedback_id}
        
    except Exception as e:
        logger.error(f"Failed to delete graph feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chunk/{chunk_id}/impact")
async def get_chunk_feedback_impact(
    chunk_id: str,
    _admin: Any = Depends(verify_admin),
):
    """Get the feedback impact score for a specific chunk."""
    try:
        await platform.neo4j_client.connect()
        
        result = await platform.neo4j_client.execute_read(
            f"""
            MATCH (f:{NodeLabel.UserFeedback.value})-[:{RelationshipType.RATES.value}]->(t:{NodeLabel.Turn.value})-[:{RelationshipType.RETRIEVED.value}]->(c:{NodeLabel.Chunk.value} {{id: $chunk_id}})
            RETURN 
                sum(CASE WHEN f.is_positive THEN 1 ELSE 0 END) as positive_count,
                sum(CASE WHEN NOT f.is_positive THEN 1 ELSE 0 END) as negative_count,
                collect(DISTINCT f.id) as feedback_ids
            """,
            parameters={"chunk_id": chunk_id}
        )
        
        if result:
            record = result[0]
            positive = record.get("positive_count", 0) or 0
            negative = record.get("negative_count", 0) or 0
            return {
                "chunk_id": chunk_id,
                "positive_count": positive,
                "negative_count": negative,
                "net_score": positive - negative,
                "feedback_ids": record.get("feedback_ids", []),
            }
        
        return {
            "chunk_id": chunk_id,
            "positive_count": 0,
            "negative_count": 0,
            "net_score": 0,
            "feedback_ids": [],
        }
        
    except Exception as e:
        logger.error(f"Failed to get chunk impact: {e}")
        return {
            "chunk_id": chunk_id,
            "positive_count": 0,
            "negative_count": 0,
            "net_score": 0,
            "feedback_ids": [],
        }

# ... (existing schemas)

class ConversationGraphItem(BaseModel):
    """Conversation item for the list view."""
    conversation_id: str
    created_at: str
    turn_count: int
    last_query: str | None
    last_active: str | None


# ... (existing endpoints)

@router.get("/conversations", response_model=list[ConversationGraphItem])
async def list_conversations(
    limit: int = 50,
    _admin: Any = Depends(verify_admin),
):
    """List conversations from the Context Graph."""
    try:
        await platform.neo4j_client.connect()
        
        result = await platform.neo4j_client.execute_read(
            f"""
            MATCH (c:{NodeLabel.Conversation.value})
            OPTIONAL MATCH (c)-[:{RelationshipType.HAS_TURN.value}]->(t:{NodeLabel.Turn.value})
            WITH c, count(t) as turn_count, collect(t) as turns
            WITH c, turn_count, 
                 [x in turns | x.created_at] as turn_dates,
                 [x in turns | x.query] as turn_queries
            WITH c, turn_count,
                 apoc.coll.max(turn_dates) as last_active,
                 turn_queries[size(turn_queries)-1] as last_query
            RETURN 
                c.id as conversation_id,
                c.created_at as created_at,
                turn_count,
                last_active,
                last_query
            ORDER BY last_active DESC
            LIMIT $limit
            """,
            parameters={"limit": limit}
        )
        
        # Fallback if apoc is not available or query is complex, verify simple cypher first
        # Simplified query avoiding APOC for safety if not installed
        """
        MATCH (c:Conversation)
        OPTIONAL MATCH (c)-[:HAS_TURN]->(t:Turn)
        WITH c, t ORDER BY t.created_at DESC
        WITH c, count(t) as turn_count, collect(t) as turns
        RETURN 
            c.id as conversation_id,
            c.created_at as created_at,
            turn_count,
            turns[0].created_at as last_active,
            turns[0].query as last_query
        ORDER BY last_active DESC
        LIMIT $limit
        """
        
        # Use the simplified one to be safe
        result = await platform.neo4j_client.execute_read(
            f"""
            MATCH (c:{NodeLabel.Conversation.value})
            OPTIONAL MATCH (c)-[:{RelationshipType.HAS_TURN.value}]->(t:{NodeLabel.Turn.value})
            WITH c, t ORDER BY t.created_at DESC
            WITH c, count(t) as turn_count, collect(t) as turns
            RETURN 
                c.id as conversation_id,
                c.created_at as created_at,
                turn_count,
                turns[0].created_at as last_active,
                turns[0].query as last_query
            ORDER BY last_active DESC
            LIMIT $limit
            """,
            parameters={"limit": limit}
        )

        items = []
        for record in result:
            items.append(ConversationGraphItem(
                conversation_id=record["conversation_id"],
                created_at=record.get("created_at") or "",
                turn_count=record.get("turn_count", 0),
                last_active=record.get("last_active"),
                last_query=record.get("last_query"),
            ))
        
        return items
        
    except Exception as e:
        logger.error(f"Failed to list conversations: {e}")
        return []
