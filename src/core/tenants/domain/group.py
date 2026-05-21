"""
Group Models
============

Intra-tenant groups for selective document access. A group scopes which
folders/documents an API key can read when group enforcement is active.
"""

from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from src.shared.kernel.models.base import Base, TimestampMixin


class Group(Base, TimestampMixin):
    """A named access group within a single tenant."""

    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_groups_tenant_name"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, server_default="true", nullable=False)

    def __repr__(self) -> str:
        return f"<Group(id={self.id}, tenant_id={self.tenant_id}, name={self.name})>"


class GroupMember(Base):
    """Membership of an API key in a group, with an in-group role."""

    __tablename__ = "group_members"

    group_id = Column(
        String, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    api_key_id = Column(
        String, ForeignKey("api_keys.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String, server_default="member", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<GroupMember(group_id={self.group_id}, api_key_id={self.api_key_id}, role={self.role})>"


class GroupFolderAccess(Base):
    """Grants a group read access to all documents in a folder."""

    __tablename__ = "group_folder_access"
    __table_args__ = (
        UniqueConstraint("group_id", "folder_id", name="uq_group_folder_access_group_folder"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    group_id = Column(
        String, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    folder_id = Column(
        String, ForeignKey("folders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    access_mode = Column(String, server_default="read", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<GroupFolderAccess(group_id={self.group_id}, folder_id={self.folder_id})>"


class GroupDocumentAccess(Base):
    """Per-document grant or deny override for a group."""

    __tablename__ = "group_document_access"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "document_id", name="uq_group_document_access_group_document"
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    group_id = Column(
        String, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    document_id = Column(
        String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    access_mode = Column(String, server_default="read", nullable=False)
    is_deny = Column(Boolean, server_default="false", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<GroupDocumentAccess(group_id={self.group_id}, document_id={self.document_id}, is_deny={self.is_deny})>"
