from typing import Protocol

from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document


class DocumentRepository(Protocol):
    """
    Port for Document persistence operations.
    Follows repository pattern to decouple domain from infrastructure.
    """

    async def get(self, document_id: str) -> Document | None:
        """Retrieve a document by ID."""
        ...

    async def save(self, document: Document) -> Document:
        """Save a new document or update an existing one."""
        ...

    async def delete(self, document: Document) -> None:
        """Delete a document."""
        ...

    async def list_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[Document]:
        """List documents for a tenant."""
        ...

    async def find_by_content_hash(self, tenant_id: str, content_hash: str) -> Document | None:
        """Find a document by content hash and tenant (for deduplication)."""
        ...

    async def update_status(
        self, document_id: str, status: str, old_status: str | None = None
    ) -> bool:
        """Atomic update of document status.

        Args:
            document_id: Document ID
            status: New status (enum value)
            old_status: Optional required current status for optimistic locking.

        Returns:
            bool: True if updated, False if not found or old_status mismatch.
        """
        ...

    async def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Retrieve chunks by IDs."""
        ...

    async def get_titles_by_ids(self, document_ids: list[str]) -> dict[str, str]:
        """Return a mapping of document_id to filename."""
        ...
