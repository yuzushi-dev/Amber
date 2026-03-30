"""
Document Sharing Service
========================

Application service for managing explicit document-level sharing from the
default tenant to child tenants.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.audit import AuditLog
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.document_share import DocumentShare
from src.core.ingestion.infrastructure.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from src.core.tenants.domain.tenant import Tenant


@dataclass(frozen=True)
class DocumentShareTargetOutput:
    tenant_id: str
    tenant_name: str | None
    share_mode: str
    created_at: datetime


@dataclass(frozen=True)
class DocumentSharesOutput:
    document_id: str
    owner_tenant_id: str
    shares: list[DocumentShareTargetOutput]


class DocumentSharingService:
    """Manage explicit document sharing for default-owned documents."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_shares(self, document_id: str) -> DocumentSharesOutput:
        document = await self._get_shareable_document(document_id)
        shares = await self._load_share_targets(document.id)
        return DocumentSharesOutput(
            document_id=document.id,
            owner_tenant_id=document.tenant_id,
            shares=shares,
        )

    async def validate_target_tenant_ids(self, tenant_ids: list[str]) -> list[str]:
        """Validate and normalize explicit share targets."""
        return await self._normalize_target_tenant_ids(tenant_ids)

    async def add_shares(
        self,
        document_id: str,
        target_tenant_ids: list[str],
        *,
        actor: str,
    ) -> DocumentSharesOutput:
        document = await self._get_shareable_document(document_id)
        normalized_targets = await self._normalize_target_tenant_ids(target_tenant_ids)
        before = await self._load_share_targets(document.id)
        before_ids = [share.tenant_id for share in before]

        to_add = [tenant_id for tenant_id in normalized_targets if tenant_id not in before_ids]
        for tenant_id in to_add:
            self._session.add(
                DocumentShare(
                    id=str(uuid4()),
                    document_id=document.id,
                    target_tenant_id=tenant_id,
                    created_by=actor,
                    share_mode="read",
                )
            )

        after_ids = before_ids + to_add
        await self._write_audit(
            actor=actor,
            action="document_shares_add",
            document_id=document.id,
            before=before_ids,
            after=after_ids,
            requested=normalized_targets,
            added=to_add,
            removed=[],
        )
        await self._session.commit()
        PostgresDocumentRepository.invalidate_visible_document_ids_cache(
            owner_tenant_id=document.tenant_id
        )
        return await self.list_shares(document.id)

    async def replace_shares(
        self,
        document_id: str,
        target_tenant_ids: list[str],
        *,
        actor: str,
    ) -> DocumentSharesOutput:
        document = await self._get_shareable_document(document_id)
        normalized_targets = await self._normalize_target_tenant_ids(target_tenant_ids)
        before = await self._load_share_targets(document.id)
        before_ids = [share.tenant_id for share in before]

        to_remove = [tenant_id for tenant_id in before_ids if tenant_id not in normalized_targets]
        to_add = [tenant_id for tenant_id in normalized_targets if tenant_id not in before_ids]

        if to_remove:
            await self._session.execute(
                delete(DocumentShare).where(
                    DocumentShare.document_id == document.id,
                    DocumentShare.target_tenant_id.in_(to_remove),
                )
            )

        for tenant_id in to_add:
            self._session.add(
                DocumentShare(
                    id=str(uuid4()),
                    document_id=document.id,
                    target_tenant_id=tenant_id,
                    created_by=actor,
                    share_mode="read",
                )
            )

        await self._write_audit(
            actor=actor,
            action="document_shares_replace",
            document_id=document.id,
            before=before_ids,
            after=normalized_targets,
            requested=normalized_targets,
            added=to_add,
            removed=to_remove,
        )
        await self._session.commit()
        PostgresDocumentRepository.invalidate_visible_document_ids_cache(
            owner_tenant_id=document.tenant_id
        )
        return await self.list_shares(document.id)

    async def remove_shares(
        self,
        document_id: str,
        target_tenant_ids: list[str],
        *,
        actor: str,
    ) -> DocumentSharesOutput:
        document = await self._get_shareable_document(document_id)
        normalized_targets = await self._normalize_target_tenant_ids(target_tenant_ids)
        before = await self._load_share_targets(document.id)
        before_ids = [share.tenant_id for share in before]

        to_remove = [tenant_id for tenant_id in before_ids if tenant_id in normalized_targets]
        if to_remove:
            await self._session.execute(
                delete(DocumentShare).where(
                    DocumentShare.document_id == document.id,
                    DocumentShare.target_tenant_id.in_(to_remove),
                )
            )

        after_ids = [tenant_id for tenant_id in before_ids if tenant_id not in normalized_targets]
        await self._write_audit(
            actor=actor,
            action="document_shares_remove",
            document_id=document.id,
            before=before_ids,
            after=after_ids,
            requested=normalized_targets,
            added=[],
            removed=to_remove,
        )
        await self._session.commit()
        PostgresDocumentRepository.invalidate_visible_document_ids_cache(
            owner_tenant_id=document.tenant_id
        )
        return await self.list_shares(document.id)

    async def _get_shareable_document(self, document_id: str) -> Document:
        result = await self._session.execute(
            select(Document).where(Document.id == document_id).limit(1)
        )
        document = result.scalars().first()
        if document is None:
            raise LookupError(f"Document {document_id} not found")
        if document.tenant_id != "default":
            raise ValueError("Only default tenant documents can be shared")
        return document

    async def _normalize_target_tenant_ids(self, tenant_ids: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for tenant_id in tenant_ids:
            normalized = str(tenant_id).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)

        if "default" in seen:
            raise ValueError("Cannot share a document to the default tenant")

        if not ordered:
            return []

        result = await self._session.execute(
            select(Tenant.id).where(Tenant.id.in_(ordered))
        )
        existing_ids = {row[0] for row in result.all()}
        missing = [tenant_id for tenant_id in ordered if tenant_id not in existing_ids]
        if missing:
            raise ValueError(f"Unknown tenant IDs: {', '.join(missing)}")

        return ordered

    async def _load_share_targets(self, document_id: str) -> list[DocumentShareTargetOutput]:
        result = await self._session.execute(
            select(
                DocumentShare.target_tenant_id,
                Tenant.name,
                DocumentShare.share_mode,
                DocumentShare.created_at,
            )
            .join(Tenant, Tenant.id == DocumentShare.target_tenant_id)
            .where(DocumentShare.document_id == document_id)
            .order_by(DocumentShare.target_tenant_id.asc())
        )
        return [
            DocumentShareTargetOutput(
                tenant_id=row.target_tenant_id,
                tenant_name=row.name,
                share_mode=row.share_mode,
                created_at=row.created_at,
            )
            for row in result.all()
        ]

    async def _write_audit(
        self,
        *,
        actor: str,
        action: str,
        document_id: str,
        before: list[str],
        after: list[str],
        requested: list[str],
        added: list[str],
        removed: list[str],
    ) -> None:
        self._session.add(
            AuditLog(
                tenant_id="default",
                actor=actor,
                action=action,
                target_type="document",
                target_id=document_id,
                changes={
                    "before": before,
                    "after": after,
                    "requested": requested,
                    "added": added,
                    "removed": removed,
                },
                metadata_json={"share_mode": "read"},
            )
        )
        await self._session.flush()
