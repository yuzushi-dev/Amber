"""
Verified Q&A Service
====================

Retrieves similar verified Q&A pairs to inject as examples in generation prompts.
"""

import logging
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.feedback import Feedback
from src.core.generation.domain.memory_models import ConversationSummary
from src.core.retrieval.application.embeddings_service import EmbeddingService

logger = logging.getLogger(__name__)


class VerifiedQAService:
    """
    Service to find similar verified Q&A pairs for prompt injection.

    Uses cosine similarity on query embeddings stored in the Feedback table.
    """

    def __init__(self, session_factory: Any, embedding_service: EmbeddingService | None = None):
        self.session_factory = session_factory
        self.embedding_service = embedding_service

    async def get_similar_examples(
        self, query: str, tenant_id: str, limit: int = 2, threshold: float = 0.7
    ) -> list[dict]:
        """
        Find similar verified Q&A pairs based on query embedding similarity.

        Args:
            query: The user's current query
            tenant_id: Tenant context
            limit: Maximum number of examples to return
            threshold: Minimum similarity threshold (0-1)

        Returns:
            List of {query, answer} dicts for prompt injection
        """
        if not self.embedding_service:
            logger.warning("No embedding service configured, skipping Q&A retrieval")
            return []

        try:
            # 1. Embed the current query
            query_embedding = await self.embedding_service.embed_text(query)
            if not query_embedding:
                return []

            # 2. Fetch all active verified feedback with embeddings
            async with self.session_factory() as session:
                stmt = (
                    select(Feedback, ConversationSummary)
                    .outerjoin(
                        ConversationSummary,
                        Feedback.metadata_json["session_id"].astext == ConversationSummary.id,
                    )
                    .where(
                        Feedback.tenant_id == tenant_id,
                        Feedback.golden_status == "VERIFIED",
                        Feedback.is_active,
                        Feedback.query_embedding.isnot(None),
                    )
                )
                result = await session.execute(stmt)
                rows = result.all()

            if not rows:
                logger.debug("No verified Q&A with embeddings found")
                return []

            # 3. Calculate similarities
            candidates = []
            query_vec = np.array(query_embedding)
            query_norm = np.linalg.norm(query_vec)

            for feedback, conversation in rows:
                stored_embedding = feedback.query_embedding
                if not stored_embedding:
                    continue

                # Cosine similarity
                stored_vec = np.array(stored_embedding)
                stored_norm = np.linalg.norm(stored_vec)

                if query_norm == 0 or stored_norm == 0:
                    continue

                similarity = float(np.dot(query_vec, stored_vec) / (query_norm * stored_norm))

                if similarity >= threshold:
                    # Extract query/answer from conversation or feedback metadata
                    qa_query = None
                    qa_answer = None

                    if conversation and conversation.metadata_:
                        qa_query = conversation.metadata_.get("query")
                        qa_answer = conversation.metadata_.get("answer")

                    if not qa_query and feedback.metadata_json:
                        qa_query = feedback.metadata_json.get("query")

                    if qa_query and qa_answer:
                        candidates.append(
                            {"query": qa_query, "answer": qa_answer, "similarity": similarity}
                        )

            # 4. Sort by similarity and return top N
            candidates.sort(key=lambda x: x["similarity"], reverse=True)

            examples = [{"query": c["query"], "answer": c["answer"]} for c in candidates[:limit]]

            logger.info(f"Found {len(examples)} similar verified Q&A examples for injection")
            return examples

        except Exception as e:
            logger.error(f"Error getting similar Q&A examples: {e}")
            return []

    async def compute_and_store_embedding(
        self, feedback_id: str, query_text: str, session: AsyncSession
    ) -> bool:
        """
        Compute and store query embedding for a feedback item.

        Called when feedback is verified to enable future similarity search.
        """
        if not self.embedding_service:
            logger.warning("No embedding service configured")
            return False

        try:
            embedding = await self.embedding_service.embed_text(query_text)
            if not embedding:
                return False

            feedback = await session.get(Feedback, feedback_id)
            if feedback:
                feedback.query_embedding = embedding
                await session.commit()
                logger.info(f"Stored query embedding for feedback {feedback_id}")
                return True
            return False

        except Exception as e:
            logger.error(f"Error storing embedding for feedback {feedback_id}: {e}")
            return False

    def format_examples_block(self, examples: list[dict]) -> str:
        """
        Format verified Q&A examples into a prompt block.

        Returns empty string if no examples.
        """
        if not examples:
            return ""

        lines = ["Here are similar questions that received positive feedback:\n"]
        for i, ex in enumerate(examples, 1):
            lines.append(f"Example {i}:")
            lines.append(f"Q: {ex['query']}")
            lines.append(f"A: {ex['answer']}")
            lines.append("")

        lines.append("Use the style and depth of these examples as a guide.\n")
        return "\n".join(lines)
