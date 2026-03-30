"""
Document Share Model
====================

Visibility grants for documents shared from the system corpus to tenant overlays.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.kernel.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.core.ingestion.domain.document import Document


class DocumentShare(Base, TimestampMixin):
    """Row-level visibility grant for a shared document."""

    __tablename__ = "document_shares"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "target_tenant_id",
            name="uq_document_shares_document_target_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    share_mode: Mapped[str] = mapped_column(String, nullable=False, default="read")


class DocumentVisibilityStatus(str, Enum):
    """Visibility classification for a document lookup."""

    VISIBLE = "visible"
    DENIED = "denied"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class VisibleDocument:
    """Document plus the visibility metadata for the current viewer tenant."""

    document: "Document"
    is_shared: bool
    owner_tenant_id: str
    visible_from_tenant_id: str
    share_mode: str | None = None
