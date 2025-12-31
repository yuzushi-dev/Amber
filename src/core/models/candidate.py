from dataclasses import dataclass, field
from typing import Any, Literal, Optional

@dataclass
class Candidate:
    """
    Unified retrieval candidate from any source (Vector, Graph, Community).
    Useful for fusion and reranking steps.
    """
    chunk_id: str
    content: str
    score: float = 0.0
    source: Literal["vector", "graph", "community", "hybrid"] = "vector"
    document_id: Optional[str] = None
    tenant_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert candidate to dictionary for API responses."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "content": self.content,
            "score": self.score,
            "source": self.source,
            "metadata": self.metadata
        }
