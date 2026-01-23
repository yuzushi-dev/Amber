from typing import Protocol, Any


class VectorStorePort(Protocol):
    """Port for vector store operations used by ingestion flows."""

    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Search for similar vectors."""
        ...

    async def upsert_chunks(self, chunks_data: list[dict[str, Any]]) -> None:
        """Upsert chunks with embeddings."""
        ...

    async def delete_by_document(self, document_id: str, tenant_id: str) -> int:
        """Delete all chunks for a document."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the vector store."""
        ...
