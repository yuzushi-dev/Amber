import logging
from typing import Any, Optional
from src.core.models.candidate import Candidate
from src.core.vector_store.milvus import MilvusVectorStore, SearchResult
from src.core.observability.tracer import trace_span

logger = logging.getLogger(__name__)

class VectorSearcher:
    """
    Handles semantic search against the Milvus vector store.
    """
    
    def __init__(self, vector_store: MilvusVectorStore):
        self.vector_store = vector_store

    @trace_span("VectorSearcher.search")
    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        document_ids: Optional[list[str]] = None,
        limit: int = 10,
        score_threshold: Optional[float] = None,
        filters: Optional[dict[str, Any]] = None
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
                # Additional filtering logic can be expanded here
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
