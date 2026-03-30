"""
Provisioning Job Model
======================

Tracks background tenant-provisioning jobs (cloning documents + vectors
from one tenant to another without re-running the ingestion pipeline).
"""

import enum
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from src.shared.kernel.models.base import Base, TimestampMixin


class ProvisioningStatus(str, enum.Enum):
    """Status of a provisioning job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # completed with non-fatal errors


class ProvisioningJob(Base, TimestampMixin):
    """
    Tracks a tenant provisioning operation.

    A provisioning job copies documents, chunks and vectors from a source
    tenant into a target tenant, allowing the target to query the same
    knowledge base without re-ingesting files.
    """

    __tablename__ = "provisioning_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    target_tenant_id = Column(String, index=True, nullable=False)
    source_tenant_id = Column(String, nullable=False)

    # Scope: null = all READY documents from source
    document_ids = Column(JSONB, nullable=True)   # list[str] | None
    folder_ids = Column(JSONB, nullable=True)      # list[str] | None
    include_graph = Column(Boolean, default=False, nullable=False)

    status = Column(
        String(20),
        default=ProvisioningStatus.PENDING.value,
        nullable=False,
    )

    # Progress percentage (0-100)
    progress = Column(Integer, default=0, nullable=False)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Error / partial-failure details
    error_message = Column(Text, nullable=True)

    # Result counters
    docs_copied = Column(Integer, default=0, nullable=False)
    chunks_copied = Column(Integer, default=0, nullable=False)
    vectors_copied = Column(Integer, default=0, nullable=False)
    graph_nodes_copied = Column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<ProvisioningJob(id={self.id}, "
            f"{self.source_tenant_id}->{self.target_tenant_id}, "
            f"status={self.status})>"
        )
