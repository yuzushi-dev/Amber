import logging
from typing import Any

from src.core.vector_store.milvus import MilvusVectorStore

logger = logging.getLogger(__name__)

class EntitySearcher:
    """
    Handles semantic search against the Entity vector store.
    This helps in finding entities related to the query, which can then be used
    as seeds for graph traversal.
    """

    def __init__(self, vector_store: MilvusVectorStore):
        # Note: We assume MilvusVectorStore is configured for the 'entities' collection
        # or we pass a specifically configured instance.
        self.vector_store = vector_store

    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        limit: int = 10,
        score_threshold: float | None = None
    ) -> list[dict[str, Any]]:
        """
        Execute semantic search over entities and return them.
        """
        try:
            # We use a dedicated collection for entity embeddings
            results = await self.vector_store.search(
                query_vector=query_vector,
                tenant_id=tenant_id,
                limit=limit,
                score_threshold=score_threshold,
                collection_name="entity_embeddings" # Assumes this is the collection name
            )

            return [
                {
                    "entity_id": r.chunk_id, # In entity collection, chunk_id is used for entity_id
                    "name": r.metadata.get("name", ""),
                    "score": r.score,
                    "description": r.metadata.get("content", ""), # Description stored in 'content'
                    "tenant_id": r.tenant_id
                }
                for r in results
            ]

        except Exception as e:
            logger.error(f"Entity search failed: {e}")
            return []
