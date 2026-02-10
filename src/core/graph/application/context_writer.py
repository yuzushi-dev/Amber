"""
Context Graph Writer
====================

Persists conversation traces and feedback to Neo4j for decision lineage.
This enables querying "why" an answer was given and how feedback influences future decisions.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.core.graph.domain.ports.graph_client import get_graph_client
from src.core.graph.domain.schema import NodeLabel, RelationshipType

logger = logging.getLogger(__name__)


class ContextGraphWriter:
    """
    Writes conversation traces ("Decision Traces") to Neo4j.

    Creates:
    - Conversation nodes: Groups of related turns
    - Turn nodes: Individual query/answer pairs with metadata
    - RETRIEVED relationships: Links turns to the chunks that were used
    - UserFeedback nodes: User ratings linked to turns
    """

    async def log_turn(
        self,
        conversation_id: str,
        tenant_id: str,
        query: str,
        answer: str,
        sources: list[dict[str, Any]] | None = None,
        trace_steps: list[dict[str, Any]] | None = None,
        model: str | None = None,
        latency_ms: float | None = None,
    ) -> str | None:
        """
        Log a conversation turn to the Context Graph.

        Args:
            conversation_id: Unique ID for the conversation thread
            tenant_id: Tenant isolation
            query: User's question
            answer: LLM-generated answer
            sources: List of source dicts with chunk_id, document_id, score
            trace_steps: Optional trace data from retrieval/generation
            model: LLM model used
            latency_ms: Total latency

        Returns:
            Turn node ID if successful, None otherwise
        """
        import uuid

        turn_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).isoformat()

        try:
            graph_client = get_graph_client()
            await graph_client.connect()

            # 1. Create or merge Conversation node
            await graph_client.execute_write(
                f"""
                MERGE (c:{NodeLabel.Conversation.value} {{id: $conv_id}})
                ON CREATE SET c.tenant_id = $tenant_id, c.created_at = $ts
                ON MATCH SET c.updated_at = $ts
                """,
                {"conv_id": conversation_id, "tenant_id": tenant_id, "ts": timestamp},
            )

            # 2. Create Turn node
            await graph_client.execute_write(
                f"""
                CREATE (t:{NodeLabel.Turn.value} {{
                    id: $turn_id,
                    conversation_id: $conv_id,
                    tenant_id: $tenant_id,
                    query: $query,
                    answer: $answer,
                    model: $model,
                    latency_ms: $latency,
                    created_at: $ts
                }})
                """,
                {
                    "turn_id": turn_id,
                    "conv_id": conversation_id,
                    "tenant_id": tenant_id,
                    "query": query[:500],
                    "answer": answer[:1000],
                    "model": model or "unknown",
                    "latency": latency_ms or 0,
                    "ts": timestamp,
                },
            )

            # 3. Link Conversation -> Turn
            await graph_client.execute_write(
                f"""
                MATCH (c:{NodeLabel.Conversation.value} {{id: $conv_id}})
                MATCH (t:{NodeLabel.Turn.value} {{id: $turn_id}})
                MERGE (c)-[:{RelationshipType.HAS_TURN.value}]->(t)
                """,
                {"conv_id": conversation_id, "turn_id": turn_id},
            )

            # 4. Link Turn -> Retrieved Chunks (Decision Trace)
            if sources:
                for source in sources:
                    chunk_id = source.get("chunk_id")
                    if chunk_id:
                        await graph_client.execute_write(
                            f"""
                            MATCH (t:{NodeLabel.Turn.value} {{id: $turn_id}})
                            MATCH (c:{NodeLabel.Chunk.value} {{id: $chunk_id}})
                            MERGE (t)-[r:{RelationshipType.RETRIEVED.value}]->(c)
                            SET r.score = $score
                            """,
                            {
                                "turn_id": turn_id,
                                "chunk_id": chunk_id,
                                "score": source.get("score", 0.0),
                            },
                        )

            logger.debug(f"Logged turn {turn_id} to Context Graph")
            return turn_id

        except Exception as e:
            logger.warning(f"Failed to log turn to Context Graph: {e}")
            return None

    async def log_feedback(
        self,
        conversation_id: str,
        turn_id: str | None,
        tenant_id: str,
        is_positive: bool,
        comment: str | None = None,
        feedback_id: str | None = None,
    ) -> str | None:
        """
        Log user feedback to the Context Graph.

        Links feedback to the specific turn if turn_id is provided,
        otherwise links to the most recent turn in the conversation.

        Args:
            conversation_id: Conversation thread ID
            turn_id: Specific turn to rate (optional)
            tenant_id: Tenant isolation
            is_positive: True for positive feedback
            comment: Optional user comment
            feedback_id: Optional existing feedback ID from Postgres

        Returns:
            Feedback node ID if successful, None otherwise
        """
        import uuid

        fb_id = feedback_id or str(uuid.uuid4())
        timestamp = datetime.now(UTC).isoformat()

        try:
            graph_client = get_graph_client()
            await graph_client.connect()

            # Create UserFeedback node
            await graph_client.execute_write(
                f"""
                CREATE (f:{NodeLabel.UserFeedback.value} {{
                    id: $fb_id,
                    tenant_id: $tenant_id,
                    is_positive: $is_positive,
                    comment: $comment,
                    created_at: $ts
                }})
                """,
                {
                    "fb_id": fb_id,
                    "tenant_id": tenant_id,
                    "is_positive": is_positive,
                    "comment": comment or "",
                    "ts": timestamp,
                },
            )

            # Link Feedback -> Turn
            if turn_id:
                await graph_client.execute_write(
                    f"""
                    MATCH (f:{NodeLabel.UserFeedback.value} {{id: $fb_id}})
                    MATCH (t:{NodeLabel.Turn.value} {{id: $turn_id}})
                    MERGE (f)-[:{RelationshipType.RATES.value}]->(t)
                    """,
                    {"fb_id": fb_id, "turn_id": turn_id},
                )
            else:
                # Find most recent turn in conversation and link
                await graph_client.execute_write(
                    f"""
                    MATCH (f:{NodeLabel.UserFeedback.value} {{id: $fb_id}})
                    MATCH (c:{NodeLabel.Conversation.value} {{id: $conv_id}})-[:{RelationshipType.HAS_TURN.value}]->(t:{NodeLabel.Turn.value})
                    WITH f, t ORDER BY t.created_at DESC LIMIT 1
                    MERGE (f)-[:{RelationshipType.RATES.value}]->(t)
                    """,
                    {"fb_id": fb_id, "conv_id": conversation_id},
                )

            logger.debug(f"Logged feedback {fb_id} to Context Graph")
            return fb_id

        except Exception as e:
            logger.warning(f"Failed to log feedback to Context Graph: {e}")
            return None

    async def get_chunk_feedback_stats(self, chunk_id: str) -> dict[str, Any]:
        """
        Get feedback statistics for a specific chunk.

        This enables the "demote negatively-rated chunks" feature.

        Returns:
            Dict with positive_count, negative_count, and net_score
        """
        try:
            graph_client = get_graph_client()
            await graph_client.connect()

            result = await graph_client.execute_read(
                f"""
                MATCH (f:{NodeLabel.UserFeedback.value})-[:{RelationshipType.RATES.value}]->(t:{NodeLabel.Turn.value})-[:{RelationshipType.RETRIEVED.value}]->(c:{NodeLabel.Chunk.value} {{id: $chunk_id}})
                RETURN
                    sum(CASE WHEN f.is_positive THEN 1 ELSE 0 END) as positive_count,
                    sum(CASE WHEN NOT f.is_positive THEN 1 ELSE 0 END) as negative_count
                """,
                {"chunk_id": chunk_id},
            )

            if result:
                record = result[0]
                positive = record.get("positive_count", 0) or 0
                negative = record.get("negative_count", 0) or 0
                return {
                    "positive_count": positive,
                    "negative_count": negative,
                    "net_score": positive - negative,
                }

            return {"positive_count": 0, "negative_count": 0, "net_score": 0}

        except Exception as e:
            logger.warning(f"Failed to get chunk feedback stats: {e}")
            return {"positive_count": 0, "negative_count": 0, "net_score": 0}


# Singleton instance
context_graph_writer = ContextGraphWriter()
