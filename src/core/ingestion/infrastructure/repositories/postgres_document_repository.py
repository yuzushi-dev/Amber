from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.ports.document_repository import DocumentRepository

class PostgresDocumentRepository(DocumentRepository):
    """
    PostgreSQL implementation of DocumentRepository using SQLAlchemy.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, document_id: str) -> Optional[Document]:
        """Retrieve a document by ID."""
        result = await self._session.execute(
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id)
        )
        return result.scalars().first()

    async def save(self, document: Document) -> Document:
        """Save a new document or update an existing one."""
        self._session.add(document)
        # We assume commit is handled by UoW or the caller if transaction management is explicit.
        # However, for a simple repository save usually implies 'add to session'.
        # Ensuring it's flushable.
        await self._session.flush()
        return document

    async def delete(self, document: Document) -> None:
        """Delete a document."""
        await self._session.delete(document)
        await self._session.flush()
        
    async def list_by_tenant(self, tenant_id: str, limit: int = 100, offset: int = 0) -> List[Document]:
        """List documents for a tenant."""
        result = await self._session.execute(
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def find_by_content_hash(self, tenant_id: str, content_hash: str) -> Optional[Document]:
        """Find a document by content hash and tenant (for deduplication)."""
        result = await self._session.execute(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.content_hash == content_hash
            )
        )
        return result.scalars().first()

    async def update_status(self, document_id: str, status: str, old_status: Optional[str] = None) -> bool:
        """Atomic update of document status."""
        from sqlalchemy import update
        from src.core.ingestion.domain.document import Document
        
        stmt = update(Document).where(Document.id == document_id)
        if old_status:
            stmt = stmt.where(Document.status == old_status)
        
        stmt = stmt.values(status=status)
        
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0

    async def get_chunks(self, chunk_ids: List[str]) -> List[Chunk]:
        """Retrieve chunks by IDs."""
        from src.core.ingestion.domain.chunk import Chunk
        if not chunk_ids:
            return []
            
        result = await self._session.execute(
            select(Chunk).where(Chunk.id.in_(chunk_ids))
        )
        return list(result.scalars().all())

    async def get_titles_by_ids(self, document_ids: List[str]) -> dict[str, str]:
        """Return a mapping of document_id to filename."""
        if not document_ids:
            return {}

        result = await self._session.execute(
            select(Document.id, Document.filename).where(Document.id.in_(document_ids))
        )
        rows = result.all()
        return {row.id: row.filename for row in rows}
