from typing import Protocol, List, Any, Optional, Dict
from dataclasses import dataclass, field

@dataclass
class SearchResult:
    """A single search result."""
    chunk_id: str
    document_id: str
    tenant_id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

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
    ) -> list[SearchResult]:
        """Search for similar vectors."""
        ...
        
    async def hybrid_search(
        self,
        dense_vector: List[float],
        sparse_vector: Dict[int, float],
        tenant_id: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        document_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Hybrid search with dense and sparse vectors."""
        ...
        
    async def upsert_chunks(self, chunks_data: List[Dict[str, Any]]) -> None:
        """Upsert chunks with embeddings."""
        ...
        
    async def disconnect(self) -> None:
        """Disconnect from the vector store."""
        ...
