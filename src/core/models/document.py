"""
Document Model
==============

Database model for stored documents.
"""

from typing import Optional

from sqlalchemy import String, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.state.machine import DocumentStatus
# We use str for ID fields to allow our custom ID types (DocumentId, TenantId) to be stored directly
# SQLAlchemy will handle them as strings


class Document(Base, TimestampMixin):
    """
    Represents an ingested document in the system.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, index=True, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False) # Path in Object Storage (MinIO)
    
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(DocumentStatus), default=DocumentStatus.INGESTED, nullable=False
    )
    
    domain: Mapped[Optional[str]] = mapped_column(String, nullable=True) # E.g., LEGAL, TECHNICAL
    
    # Source tracking
    source_type: Mapped[str] = mapped_column(String, default="file", nullable=False)  # file, url, connector
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Original URL if from URL/connector
    
    # Metadata includes: page_count, custom tags, source info, processing_stats
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}", nullable=False)

    # Error tracking for failed processing
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship to chunks
    # Relationship to chunks
    chunks: Mapped[list["Chunk"]] = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document(id={self.id}, filename={self.filename}, status={self.status})>"
