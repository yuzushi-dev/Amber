import time
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.document_share import (
    DocumentShare,
    DocumentVisibilityStatus,
    VisibleDocument,
)
from src.core.ingestion.domain.folder import Folder
from src.core.ingestion.domain.ports.document_repository import DocumentRepository


class PostgresDocumentRepository(DocumentRepository):
    """
    PostgreSQL implementation of DocumentRepository using SQLAlchemy.
    """

    _visible_document_ids_cache: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {}
    _visible_document_ids_cache_ttl_seconds: float = 30.0

    def __init__(self, session: AsyncSession):
        self._session = session

    @classmethod
    def _visible_document_ids_cache_key(
        cls,
        viewer_tenant_id: str,
        owner_tenant_id: str,
    ) -> tuple[str, str]:
        return (str(viewer_tenant_id), str(owner_tenant_id))

    @classmethod
    def _get_cached_visible_document_ids(
        cls,
        viewer_tenant_id: str,
        owner_tenant_id: str,
    ) -> list[str] | None:
        key = cls._visible_document_ids_cache_key(viewer_tenant_id, owner_tenant_id)
        entry = cls._visible_document_ids_cache.get(key)
        if entry is None:
            return None

        expires_at, document_ids = entry
        if expires_at <= time.monotonic():
            cls._visible_document_ids_cache.pop(key, None)
            return None

        return list(document_ids)

    @classmethod
    def _set_cached_visible_document_ids(
        cls,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        document_ids: list[str],
    ) -> None:
        key = cls._visible_document_ids_cache_key(viewer_tenant_id, owner_tenant_id)
        cls._visible_document_ids_cache[key] = (
            time.monotonic() + cls._visible_document_ids_cache_ttl_seconds,
            tuple(document_ids),
        )

    @classmethod
    def invalidate_visible_document_ids_cache(
        cls,
        *,
        viewer_tenant_id: str | None = None,
        owner_tenant_id: str | None = None,
    ) -> None:
        if viewer_tenant_id is None and owner_tenant_id is None:
            cls._visible_document_ids_cache.clear()
            return

        keys_to_delete = [
            key
            for key in cls._visible_document_ids_cache
            if (viewer_tenant_id is None or key[0] == str(viewer_tenant_id))
            and (owner_tenant_id is None or key[1] == str(owner_tenant_id))
        ]
        for key in keys_to_delete:
            cls._visible_document_ids_cache.pop(key, None)

    async def get(self, document_id: str) -> Document | None:
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
        await self._session.flush()
        return document

    async def delete(self, document: Document) -> None:
        """Delete a document."""
        await self._session.delete(document)
        await self._session.flush()

    async def list_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[Document]:
        """List documents for a tenant."""
        result = await self._session.execute(
            select(Document).where(Document.tenant_id == tenant_id).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def list_visible_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[VisibleDocument]:
        """List documents visible to a tenant, including shared documents."""
        result = await self._session.execute(
            select(Document, DocumentShare.share_mode)
            .options(selectinload(Document.folder))
            .outerjoin(
                DocumentShare,
                and_(
                    DocumentShare.document_id == Document.id,
                    DocumentShare.target_tenant_id == tenant_id,
                ),
            )
            .where(
                or_(
                    Document.tenant_id == tenant_id,
                    DocumentShare.target_tenant_id == tenant_id,
                )
            )
            .limit(limit)
            .offset(offset)
        )
        return [
            self._to_visible_document(document, tenant_id, share_mode)
            for document, share_mode in result.all()
        ]

    async def get_visible(self, document_id: str, tenant_id: str) -> VisibleDocument | None:
        """Get a document visible to a tenant, including shared documents."""
        result = await self._session.execute(
            select(Document, DocumentShare.share_mode)
            .options(selectinload(Document.folder))
            .outerjoin(
                DocumentShare,
                and_(
                    DocumentShare.document_id == Document.id,
                    DocumentShare.target_tenant_id == tenant_id,
                ),
            )
            .where(Document.id == document_id)
            .where(
                or_(
                    Document.tenant_id == tenant_id,
                    DocumentShare.target_tenant_id == tenant_id,
                )
            )
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        document, share_mode = row
        return self._to_visible_document(document, tenant_id, share_mode)

    async def list_visible_document_ids(
        self,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        candidate_document_ids: list[str] | None = None,
    ) -> list[str]:
        """List visible document IDs for a viewer, scoped to a specific owner tenant."""
        if candidate_document_ids == []:
            return []

        if owner_tenant_id != viewer_tenant_id:
            cached_document_ids = self._get_cached_visible_document_ids(
                viewer_tenant_id,
                owner_tenant_id,
            )
            if cached_document_ids is not None:
                if candidate_document_ids is None:
                    return cached_document_ids
                allowed_document_ids = set(cached_document_ids)
                return [
                    document_id
                    for document_id in candidate_document_ids
                    if document_id in allowed_document_ids
                ]

        stmt = (
            select(Document.id)
            .outerjoin(
                DocumentShare,
                and_(
                    DocumentShare.document_id == Document.id,
                    DocumentShare.target_tenant_id == viewer_tenant_id,
                ),
            )
            .where(Document.tenant_id == owner_tenant_id)
        )

        if candidate_document_ids is not None:
            stmt = stmt.where(Document.id.in_(candidate_document_ids))

        if owner_tenant_id != viewer_tenant_id:
            stmt = stmt.where(DocumentShare.target_tenant_id == viewer_tenant_id)

        result = await self._session.execute(stmt)
        visible_document_ids = list(result.scalars().all())

        if owner_tenant_id != viewer_tenant_id and candidate_document_ids is None:
            self._set_cached_visible_document_ids(
                viewer_tenant_id,
                owner_tenant_id,
                visible_document_ids,
            )

        return visible_document_ids

    async def classify_visibility(
        self,
        document_id: str,
        viewer_tenant_id: str,
        shared_owner_tenant_ids: list[str] | None = None,
    ) -> DocumentVisibilityStatus:
        """Classify a missing visible lookup as denied vs not found."""
        owner_tenant_ids = [viewer_tenant_id]
        for owner_tenant_id in shared_owner_tenant_ids or []:
            normalized = str(owner_tenant_id)
            if normalized not in owner_tenant_ids:
                owner_tenant_ids.append(normalized)

        for owner_tenant_id in owner_tenant_ids:
            if await self._document_exists_in_owner_scope(
                document_id=document_id,
                owner_tenant_id=owner_tenant_id,
                restore_tenant_id=viewer_tenant_id,
            ):
                return DocumentVisibilityStatus.DENIED

        return DocumentVisibilityStatus.NOT_FOUND

    async def _document_exists_in_owner_scope(
        self,
        document_id: str,
        owner_tenant_id: str,
        restore_tenant_id: str,
    ) -> bool:
        """Check existence in one owner scope by temporarily switching RLS tenant context."""
        current_tenant_result = await self._session.execute(
            text("SELECT current_setting('app.current_tenant', true)")
        )
        current_tenant = current_tenant_result.scalar_one_or_none() or restore_tenant_id

        try:
            if owner_tenant_id != current_tenant:
                await self._session.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                    {"tenant_id": owner_tenant_id},
                )

            result = await self._session.execute(
                select(Document.id)
                .where(Document.id == document_id, Document.tenant_id == owner_tenant_id)
                .limit(1)
            )
            return result.scalar_one_or_none() is not None
        finally:
            if owner_tenant_id != current_tenant:
                await self._session.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                    {"tenant_id": current_tenant},
                )

    async def find_by_content_hash(self, tenant_id: str, content_hash: str) -> Document | None:
        """Find a document by content hash and tenant (for deduplication)."""
        result = await self._session.execute(
            select(Document).where(
                Document.tenant_id == tenant_id, Document.content_hash == content_hash
            )
        )
        return result.scalars().first()

    async def update_status(
        self, document_id: str, status: str, old_status: str | None = None
    ) -> bool:
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

    async def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Retrieve chunks by IDs."""
        from src.core.ingestion.domain.chunk import Chunk

        if not chunk_ids:
            return []

        result = await self._session.execute(select(Chunk).where(Chunk.id.in_(chunk_ids)))
        return list(result.scalars().all())

    async def get_titles_by_ids(self, document_ids: list[str]) -> dict[str, str]:
        """Return a mapping of document_id to filename."""
        if not document_ids:
            return {}

        result = await self._session.execute(
            select(Document.id, Document.filename).where(Document.id.in_(document_ids))
        )
        rows = result.all()
        return {row.id: row.filename for row in rows}

    @staticmethod
    def _to_visible_document(
        document: Document, viewer_tenant_id: str, share_mode: str | None
    ) -> VisibleDocument:
        is_shared = document.tenant_id != viewer_tenant_id
        return VisibleDocument(
            document=document,
            is_shared=is_shared,
            owner_tenant_id=document.tenant_id,
            visible_from_tenant_id=viewer_tenant_id,
            share_mode=share_mode if is_shared else None,
        )

    async def get_folder_name(self, folder_id: str) -> str | None:
        """Return the display name of a folder by its ID, or None if not found."""
        folder = await self._session.get(Folder, folder_id)
        return folder.name if folder else None

    async def list_visible_document_ids_by_taxonomy(
        self,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        candidate_document_ids: list[str] | None = None,
        edition: str | None = None,
        audience: str | None = None,
        source_family: str | None = None,
    ) -> list[str]:
        """List visible document IDs filtered by taxonomy fields stored in metadata JSONB.

        Reuses the existing ACL visibility logic and adds JSONB taxonomy predicates.
        Only filters by a field when the parameter is explicitly provided (not None).
        unknown-edition/audience docs are excluded when a filter is active.
        """
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB

        if candidate_document_ids == []:
            return []

        stmt = (
            select(Document.id)
            .outerjoin(
                DocumentShare,
                and_(
                    DocumentShare.document_id == Document.id,
                    DocumentShare.target_tenant_id == viewer_tenant_id,
                ),
            )
            .where(Document.tenant_id == owner_tenant_id)
        )

        if candidate_document_ids is not None:
            stmt = stmt.where(Document.id.in_(candidate_document_ids))

        if owner_tenant_id != viewer_tenant_id:
            stmt = stmt.where(DocumentShare.target_tenant_id == viewer_tenant_id)

        if edition is not None:
            stmt = stmt.where(
                Document.metadata_["taxonomy"]["edition"].astext == edition
            )

        if audience is not None:
            stmt = stmt.where(
                Document.metadata_["taxonomy"]["audience"].astext == audience
            )

        if source_family is not None:
            stmt = stmt.where(
                Document.metadata_["taxonomy"]["source_family"].astext == source_family
            )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

