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

    _visible_document_ids_cache: dict[
        tuple[str, str, frozenset[str]], tuple[float, tuple[str, ...]]
    ] = {}
    _visible_document_ids_cache_ttl_seconds: float = 30.0

    def __init__(self, session: AsyncSession):
        self._session = session

    @classmethod
    def _visible_document_ids_cache_key(
        cls,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        group_ids: list[str] | None = None,
    ) -> tuple[str, str, frozenset[str]]:
        return (str(viewer_tenant_id), str(owner_tenant_id), frozenset(group_ids or []))

    @classmethod
    def _get_cached_visible_document_ids(
        cls,
        viewer_tenant_id: str,
        owner_tenant_id: str,
        group_ids: list[str] | None = None,
    ) -> list[str] | None:
        key = cls._visible_document_ids_cache_key(viewer_tenant_id, owner_tenant_id, group_ids)
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
        group_ids: list[str] | None = None,
    ) -> None:
        key = cls._visible_document_ids_cache_key(viewer_tenant_id, owner_tenant_id, group_ids)
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

    async def list_visible_by_tenant_paged(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        status_filter: str | None = None,
        folder_id: str | None = None,
        source_type: str | None = None,
        sort_column: str = "created_at",
        sort_dir: str = "desc",
    ) -> tuple[list[VisibleDocument], int]:
        """Paged list of visible documents for a tenant, with filters + sort + total count."""
        from sqlalchemy import func as _func

        sort_map = {
            "created_at": Document.created_at,
            "filename": Document.filename,
            "status": Document.status,
        }
        sort_col = sort_map.get(sort_column, Document.created_at)
        order_clause = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

        base = (
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
        )

        if search:
            pattern = f"%{search}%"
            base = base.where(Document.filename.ilike(pattern))
        if status_filter:
            base = base.where(Document.status == status_filter)
        if folder_id:
            base = base.where(Document.folder_id == folder_id)
        if source_type:
            base = base.where(Document.source_type == source_type)

        count_subq = base.with_only_columns(_func.count(Document.id)).order_by(None)
        total_res = await self._session.execute(count_subq)
        total = int(total_res.scalar() or 0)

        paged = base.order_by(order_clause).limit(limit).offset(offset)
        result = await self._session.execute(paged)
        items = [
            self._to_visible_document(document, tenant_id, share_mode)
            for document, share_mode in result.all()
        ]
        return items, total

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
        group_ids: list[str] | None = None,
        enforce_groups: bool = False,
    ) -> list[str]:
        """List visible document IDs for a viewer, scoped to a specific owner tenant."""
        if candidate_document_ids == []:
            return []

        if enforce_groups and owner_tenant_id == viewer_tenant_id:
            if not group_ids:
                return []
            from src.core.tenants.domain.group import (
                GroupDocumentAccess,
                GroupFolderAccess,
            )

            folder_subq = (
                select(Document.id)
                .join(GroupFolderAccess, GroupFolderAccess.folder_id == Document.folder_id)
                .where(
                    GroupFolderAccess.group_id.in_(group_ids),
                    GroupFolderAccess.tenant_id == owner_tenant_id,
                    Document.tenant_id == owner_tenant_id,
                )
            )
            doc_grant_subq = (
                select(GroupDocumentAccess.document_id)
                .where(
                    GroupDocumentAccess.group_id.in_(group_ids),
                    GroupDocumentAccess.is_deny == False,  # noqa: E712
                    GroupDocumentAccess.tenant_id == owner_tenant_id,
                )
            )
            deny_subq = (
                select(GroupDocumentAccess.document_id)
                .where(
                    GroupDocumentAccess.group_id.in_(group_ids),
                    GroupDocumentAccess.is_deny == True,  # noqa: E712
                    GroupDocumentAccess.tenant_id == owner_tenant_id,
                )
            )
            stmt = select(Document.id).where(
                Document.tenant_id == owner_tenant_id,
                or_(Document.id.in_(folder_subq), Document.id.in_(doc_grant_subq)),
                Document.id.not_in(deny_subq),
            )
            if candidate_document_ids is not None:
                stmt = stmt.where(Document.id.in_(candidate_document_ids))
            result = await self._session.execute(stmt)
            return list(result.scalars().all())

        if owner_tenant_id != viewer_tenant_id:
            cached_document_ids = self._get_cached_visible_document_ids(
                viewer_tenant_id,
                owner_tenant_id,
                group_ids,
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
                group_ids,
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
        edition: str | list[str] | None = None,
        audience: str | None = None,
        source_family: str | None = None,
    ) -> list[str]:
        """List visible document IDs filtered by taxonomy fields stored in metadata JSONB.

        Reuses the existing ACL visibility logic and adds JSONB taxonomy predicates.
        Only filters by a field when the parameter is explicitly provided (not None).
        unknown-edition/audience docs are excluded when a filter is active.

        ``edition`` may be a single value (exact match) or a list/tuple of values
        (matches any, i.e. SQL ``IN``) — used when a query references both editions.
        """

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
            _edition_col = Document.metadata_["taxonomy"]["edition"].astext
            if isinstance(edition, (list, tuple, set)):
                _editions = list(edition)
                # Single-element list behaves like a scalar exact match.
                stmt = stmt.where(
                    _edition_col == _editions[0]
                    if len(_editions) == 1
                    else _edition_col.in_(_editions)
                )
            else:
                stmt = stmt.where(_edition_col == edition)

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

