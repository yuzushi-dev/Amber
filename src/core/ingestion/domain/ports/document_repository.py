from typing import Protocol

from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document, DocumentGeneration
from src.core.ingestion.domain.document_share import VisibleDocument


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

    async def save_generation(self, generation: DocumentGeneration) -> DocumentGeneration:
        """Persist a document artifact generation without publishing it."""
        ...

    async def get_generation(self, generation_id: str) -> DocumentGeneration | None:
        """Retrieve one artifact generation."""
        ...

    async def save_chunks(self, chunks: list[Chunk]) -> None:
        """Persist staging chunks without replacing published chunks."""
        ...

    async def mark_generation_failed(self, generation_id: str, error_message: str) -> None:
        """Mark only the staging generation failed."""
        ...

    async def delete_chunks_by_generation(self, generation_id: str) -> None:
        """Delete any chunks already written for this generation (retry cleanup)."""
        ...

    async def delete(self, document: Document) -> None:
        """Delete a document."""
        ...

    async def list_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[Document]:
        """List documents for a tenant."""
        ...

    async def list_visible_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[VisibleDocument]:
        """List documents visible to a tenant, including shared ones."""
        ...

    async def get_visible(self, document_id: str, tenant_id: str) -> VisibleDocument | None:
        """Get a document visible to a tenant, including shared ones."""
        ...

    async def list_visible_document_ids(
        self,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        candidate_document_ids: list[str] | None = None,
        group_ids: list[str] | None = None,
        enforce_groups: bool = False,
    ) -> list[str]:
        """List visible document IDs for a viewer, scoped to a specific owner tenant."""
        ...

    async def find_by_content_hash(self, tenant_id: str, content_hash: str) -> Document | None:
        """Find a document by content hash and tenant (for deduplication)."""
        ...

    async def find_by_source_url(self, tenant_id: str, source_url: str) -> Document | None:
        """Find a document by source URL and tenant (for connector-based dedup)."""
        ...

    async def find_by_filename(self, tenant_id: str, filename: str) -> Document | None:
        """Find the most recent document by filename and tenant (for dedup).

        Pre-existing filename duplicates are not cleaned up as part of this
        lookup, so implementations must tolerate more than one matching row
        and deterministically return the newest (created_at DESC).
        """
        ...

    async def list_non_ready_document_ids_with_chunks(self, tenant_id: str) -> list[str]:
        """List distinct IDs of non-READY documents for a tenant that already have chunks.

        Used as a retrieval-time blocklist: Milvus has no document status field,
        so non-READY documents whose stale/duplicate chunks are still indexed
        must be excluded by ID.
        """
        ...

    async def update_status(
        self,
        document_id: str,
        status: str,
        old_status: str | None = None,
        attempt_id: str | None = None,
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

    async def claim_processing_attempt(
        self,
        document_id: str,
        attempt_id: str,
        old_status: str,
        pending_generation_id: str | None,
    ) -> bool:
        """Claim one document attempt only if no worker currently owns it."""
        ...

    async def release_processing_attempt(self, document_id: str, attempt_id: str) -> bool:
        """Release the attempt only if it still owns the document."""
        ...

    async def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Retrieve only chunks from each document's published generation."""
        ...

    async def publish_generation(
        self, document_id: str, generation: DocumentGeneration, attempt_id: str
    ) -> bool:
        """Atomically publish the document's expected pending generation."""
        ...

    async def get_titles_by_ids(self, document_ids: list[str]) -> dict[str, str]:
        """Return a mapping of document_id to filename."""
        ...

    async def get_folder_name(self, folder_id: str) -> str | None:
        """Return the display name of a folder by its ID, or None if not found."""
        ...

    async def list_visible_document_ids_by_taxonomy(
        self,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        candidate_document_ids: list[str] | None = None,
        edition: str | list[str] | None = None,
        audience: str | None = None,
        source_family: str | None = None,
    ) -> list[str]:
        """List visible document IDs filtered by taxonomy (edition/audience/source_family).

        ``edition`` accepts a single value (exact match) or a list of values
        (match any) for dual-edition queries.
        """
        ...
