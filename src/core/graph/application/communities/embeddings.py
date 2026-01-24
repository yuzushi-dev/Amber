import logging
from typing import Any

from src.core.retrieval.application.embeddings_service import EmbeddingService
from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort

logger = logging.getLogger(__name__)

class CommunityEmbeddingService:
    """
    Handles embedding and storage of community summaries in the vector store.
    """

    FIELD_COMMUNITY_ID = "community_id"
    FIELD_TENANT_ID = "tenant_id"
    FIELD_LEVEL = "level"
    FIELD_TITLE = "title"
    FIELD_SUMMARY = "summary"
    FIELD_VECTOR = "vector"

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStorePort,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store

    async def embed_and_store_community(self, community_data: dict[str, Any]):
        """
        Embeds a community summary and stores it in the vector store.

        Args:
            community_data: Dict with id, tenant_id, level, title, summary
        """
        text_to_embed = f"{community_data['title']}: {community_data['summary']}"
        embedding = await self.embedding_service.embed_single(text_to_embed)

        try:
            await self.vector_store.upsert_chunks([
                {
                    "chunk_id": community_data["id"],
                    "document_id": community_data["id"],
                    "tenant_id": community_data["tenant_id"],
                    "content": community_data["summary"],
                    "embedding": embedding,
                    "title": community_data["title"],
                    "level": community_data["level"],
                }
            ])
            logger.info(f"Stored embedding for community {community_data['id']}")
        except Exception as e:
            logger.error(f"Failed to store community embedding: {e}")
            raise

    async def search_communities(
        self,
        query_vector: list[float],
        tenant_id: str,
        level: int | None = None,
        limit: int = 5
    ) -> list[dict[str, Any]]:
        """
        Searches for communities semantically similar to the query.
        """
        filters = {"level": level} if level is not None else None
        results = await self.vector_store.search(
            query_vector=query_vector,
            tenant_id=tenant_id,
            limit=limit,
            filters=filters,
        )

        return [
            {
                "id": r.chunk_id,
                "title": r.metadata.get("title"),
                "summary": r.metadata.get("content", ""),
                "level": r.metadata.get("level"),
                "score": r.score,
            }
            for r in results
        ]
