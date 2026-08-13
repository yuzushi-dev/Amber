import logging
from typing import Any

from src.core.retrieval.domain.candidate import Candidate
from src.core.retrieval.domain.ports.vector_store_port import VectorStorePort
from src.shared.kernel.observability import trace_span

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
        exclude_document_ids: list[str] | None = None,
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
                exclude_document_ids=exclude_document_ids,
            )

            return [
                Candidate(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    tenant_id=r.tenant_id,
                    content=r.metadata.get("content", ""),
                    score=r.score,
                    source="vector",
                    metadata={
                        **r.metadata,
                        **({"generation_id": r.generation_id} if r.generation_id is not None else {}),
                    },
                )
                for r in results
            ]

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    @trace_span("VectorSearcher.hybrid_search")
    async def hybrid_search(
        self,
        query_vector: list[float],
        sparse_vector: dict[int, float],
        tenant_id: str,
        document_ids: list[str] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
        filters: dict[str, Any] | None = None,
        collection_name: str | None = None,
        exclude_document_ids: list[str] | None = None,
    ) -> list[Candidate]:
        """
        Execute hybrid (dense + sparse) search and return results as Candidates.

        Note: score_threshold here is on the hybrid fusion scale (Milvus RRF/weighted
        rerank output, typically ~0.01-0.03), NOT the cosine similarity scale (0-1)
        used by dense search(). Callers must NOT pass a tenant's cosine
        similarity_threshold through unchanged - it would filter out every hybrid
        result. Defaults to None (no filtering, matching prior behavior) until a
        properly-scaled hybrid threshold is derived.
        """
        try:
            results = await self.vector_store.hybrid_search(
                dense_vector=query_vector,
                sparse_vector=sparse_vector,
                tenant_id=tenant_id,
                document_ids=document_ids,
                limit=limit,
                filters=filters,
                collection_name=collection_name,
                score_threshold=score_threshold,
                exclude_document_ids=exclude_document_ids,
            )

            return [
                Candidate(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    tenant_id=r.tenant_id,
                    content=r.metadata.get("content", ""),
                    score=r.score,
                    source="hybrid",
                    metadata={
                        **r.metadata,
                        **({"generation_id": r.generation_id} if r.generation_id is not None else {}),
                    },
                )
                for r in results
            ]

        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            # Fallback to dense search. Do NOT forward score_threshold: it is on the
            # hybrid fusion scale (~0.01-0.03), while dense search filters on cosine
            # (0-1) — applying it here would be a scale mismatch.
            return await self.search(
                query_vector=query_vector,
                tenant_id=tenant_id,
                document_ids=document_ids,
                limit=limit,
                filters=filters,
                collection_name=collection_name,
                exclude_document_ids=exclude_document_ids,
            )
