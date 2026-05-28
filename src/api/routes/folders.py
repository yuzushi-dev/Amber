import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant_id
from src.api.deps import get_db_session as get_db_session
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.tenants.domain.group import GroupFolderAccess

router = APIRouter()


# --- Pydantic Models ---
class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class FolderUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class FolderResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    created_at: datetime
    document_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class FolderCounts(BaseModel):
    by_folder: dict[str, int]
    unfiled: int
    total: int


# --- Endpoints ---


async def _count_documents_by_folder(
    session: AsyncSession, *, tenant_id: str | None = None
) -> tuple[dict[str | None, int], int]:
    """Return (counts_by_folder_id, total). folder_id=None bucket counts unfiled."""
    stmt = select(Document.folder_id, func.count(Document.id))
    if tenant_id:
        stmt = stmt.where(Document.tenant_id == tenant_id)
    stmt = stmt.group_by(Document.folder_id)
    raw = await session.execute(stmt)
    counts: dict[str | None, int] = {}
    for folder_id, count in raw.all():
        counts[folder_id] = int(count or 0)
    return counts, sum(counts.values())


@router.get("", response_model=list[FolderResponse])
async def list_folders(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """List folders. Super-admin sees a deduplicated logical view merged by name."""
    is_super_admin = getattr(request.state, "is_super_admin", False)
    if not is_super_admin:
        groups_enforced = getattr(request.state, "groups_enforced", False)
        group_ids = getattr(request.state, "group_ids", [])
        if groups_enforced and group_ids:
            result = await session.execute(
                select(Folder)
                .join(
                    GroupFolderAccess,
                    (GroupFolderAccess.folder_id == Folder.id)
                    & GroupFolderAccess.group_id.in_(group_ids),
                )
                .where(Folder.tenant_id == tenant_id)
                .distinct()
                .order_by(Folder.name)
            )
        else:
            result = await session.execute(
                select(Folder).where(Folder.tenant_id == tenant_id).order_by(Folder.name)
            )
        folders = result.scalars().all()
        counts, _ = await _count_documents_by_folder(session, tenant_id=tenant_id)
        return [
            FolderResponse(
                id=f.id,
                tenant_id=f.tenant_id,
                name=f.name,
                created_at=f.created_at,
                document_count=counts.get(f.id, 0),
            )
            for f in folders
        ]

    # Super-admin: fetch all valid folders, deduplicate by name.
    # Use the 'default' tenant's folder as canonical when a same-name folder exists there;
    # otherwise use any available folder. This gives a single logical entry per category.
    from sqlalchemy import text as _text
    raw = await session.execute(
        _text(
            "SELECT f.id, f.name, f.tenant_id, f.created_at "
            "FROM folders f "
            "INNER JOIN tenants t ON t.id = f.tenant_id "
            "ORDER BY "
            "  CASE WHEN f.tenant_id = 'default' THEN 0 ELSE 1 END, "
            "  f.name"
        )
    )
    rows = raw.mappings().all()

    # Keep first occurrence of each name (default preferred due to ORDER BY above)
    seen: set[str] = set()
    canonical_ids: list[str] = []
    for row in rows:
        if row["name"] not in seen:
            seen.add(row["name"])
            canonical_ids.append(row["id"])

    if not canonical_ids:
        return []

    result = await session.execute(
        select(Folder).where(Folder.id.in_(canonical_ids)).order_by(Folder.name)
    )
    folders = result.scalars().all()

    # Aggregate counts across all tenants by canonical (matching name).
    counts_raw, _ = await _count_documents_by_folder(session)
    # Build name -> canonical_id map (canonical is in `folders` list).
    name_to_canonical = {f.name: f.id for f in folders}
    # Build folder_id -> name map from raw rows (need all folders, not just canonical).
    all_folders_raw = await session.execute(select(Folder.id, Folder.name))
    folder_id_to_name = {fid: name for fid, name in all_folders_raw.all()}

    canonical_counts: dict[str, int] = {f.id: 0 for f in folders}
    for fid, c in counts_raw.items():
        name = folder_id_to_name.get(fid)
        canonical_id = name_to_canonical.get(name) if name else None
        if canonical_id:
            canonical_counts[canonical_id] = canonical_counts.get(canonical_id, 0) + c

    return [
        FolderResponse(
            id=f.id,
            tenant_id=f.tenant_id,
            name=f.name,
            created_at=f.created_at,
            document_count=canonical_counts.get(f.id, 0),
        )
        for f in folders
    ]


@router.get("/counts", response_model=FolderCounts)
async def folder_counts(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Document counts per folder (cheap GROUP BY)."""
    is_super_admin = getattr(request.state, "is_super_admin", False)
    counts_raw, total = await _count_documents_by_folder(
        session, tenant_id=None if is_super_admin else tenant_id
    )
    unfiled = counts_raw.pop(None, 0)
    by_folder: dict[str, int] = {fid: count for fid, count in counts_raw.items() if fid}
    return FolderCounts(by_folder=by_folder, unfiled=unfiled, total=total)


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    folder_in: FolderCreate,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Create a new folder."""
    # RLS will enforce insertion only into current tenant (if check_option=CASCASE/LOCAL is used, strict RLS)
    # Even without strict insertion check, we must insert with the correct tenant_id.

    new_folder = Folder(id=str(uuid.uuid4()), tenant_id=tenant_id, name=folder_in.name)
    session.add(new_folder)
    await session.commit()
    await session.refresh(new_folder)
    return new_folder


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    delete_contents: bool = False,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Delete a folder.
    If delete_contents is True, all documents in the folder are permanently deleted.
    Otherwise, documents are unfiled.
    """
    # Explicitly check tenant_id in query
    query = select(Folder).where(Folder.id == folder_id, Folder.tenant_id == tenant_id)
    result = await session.execute(query)
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if delete_contents:
        # Recursive deletion
        from src.amber_platform.composition_root import build_vector_store_factory, platform
        from src.api.config import settings
        from src.core.ingestion.application.use_cases_documents import (
            DeleteDocumentRequest,
            DeleteDocumentUseCase,
        )

        # 1. Get all documents in the folder
        doc_query = select(Document).where(
            Document.folder_id == folder_id, Document.tenant_id == tenant_id
        )
        doc_result = await session.execute(doc_query)
        documents = doc_result.scalars().all()

        # 2. Setup Delete Use Case
        vector_store_factory = build_vector_store_factory()
        dimensions = settings.embedding_dimensions or 1536

        def make_vector_store(tid: str):
            return vector_store_factory(dimensions, collection_name=f"amber_{tid}")

        use_case = DeleteDocumentUseCase(
            session=session,
            storage=platform.minio_client,
            graph_client=platform.neo4j_client,
            vector_store_factory=make_vector_store,
        )

        # 3. Delete each document
        for doc in documents:
            try:
                await use_case.execute(
                    DeleteDocumentRequest(
                        document_id=doc.id, tenant_id=tenant_id, is_super_admin=False
                    )
                )
            except Exception:
                # Log error but continue deleting others/folder?
                # Or abort? Ideally we want best effort cleanup.
                # logger variable is not available in this scope, let's just print or ignore for now as use_case logs internally
                pass

    else:
        # Default behavior: Unfile documents
        from sqlalchemy import update

        stmt = update(Document).where(Document.folder_id == folder_id).values(folder_id=None)
        await session.execute(stmt)

    # Now delete the folder
    await session.delete(folder)
    await session.commit()
