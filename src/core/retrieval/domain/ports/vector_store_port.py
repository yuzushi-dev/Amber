from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SearchResult:
    """A single search result."""

    chunk_id: str
    document_id: str
    tenant_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    score_type: str = "cosine"
    source: str = "vector"
    generation_id: str | None = None


class VectorStorePort(Protocol):
    """
    Port for Vector Store operations.
    """

    async def connect(self) -> None:
        """Connect to the vector store."""
        ...

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
    ) -> list[SearchResult]:
        """Search for similar vectors.

        exclude_document_ids (if given) is a blocklist applied inside the
        store's native query expression, not a post-filter (a post-filter
        would consume `limit` before excluding anything).
        """
        ...

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector: dict[int, float],
        tenant_id: str,
        document_ids: list[str] | None = None,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        rrf_k: int = 60,
        collection_name: str | None = None,
        score_threshold: float | None = None,
        exclude_document_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        """
        Hybrid search with dense and sparse vectors.

        score_threshold (if given) is on the fusion/reranker scale, NOT the cosine
        scale used by `search()` - do not reuse a cosine similarity_threshold here.
        exclude_document_ids: see `search()`.
        """
        ...

    async def upsert_chunks(self, chunks_data: list[dict[str, Any]]) -> None:
        """Upsert chunks with embeddings."""
        ...

    async def delete_by_generation(
        self, document_id: str, tenant_id: str, generation_id: str
    ) -> int:
        """Delete chunks belonging to one unpublished document generation."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the vector store."""
        ...
