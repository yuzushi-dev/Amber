import logging
from typing import Any

from src.core.retrieval.domain.candidate import Candidate
from src.shared.kernel.observability import trace_span
from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort

logger = logging.getLogger(__name__)

class VectorSearcher:
    """
    Handles semantic search against a vector store.
    """

    def __init__(self, vector_store: VectorStorePort):
        self.vector_store = vector_store

    @trace_span("VectorSearcher.search")
    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        document_ids: list[str] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
        filters: dict[str, Any] | None = None,
        collection_name: str | None = None,
    ) -> list[Candidate]:
        """
        Execute semantic search and return results as Candidates.
        """
        try:
            results = await self.vector_store.search(
                query_vector=query_vector,
                tenant_id=tenant_id,
                document_ids=document_ids,
                limit=limit,
                score_threshold=score_threshold,
                filters=filters,
                collection_name=collection_name,
            )

            return [
                Candidate(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    tenant_id=r.tenant_id,
                    content=r.metadata.get("content", ""),
                    score=r.score,
                    source="vector",
                    metadata=r.metadata
                )
                for r in results
            ]

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
