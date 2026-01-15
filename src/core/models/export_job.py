"""
Export Job Model
================

Tracks background export jobs for conversation data export.
"""

import enum
from uuid import uuid4

from sqlalchemy import Column, DateTime, Enum, String, Text

from src.core.models.base import Base, TimestampMixin


class ExportStatus(str, enum.Enum):
    """Status of an export job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportJob(Base, TimestampMixin):
    """
    Tracks conversation export jobs.
    """
    __tablename__ = "export_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=True)  # Optional: who requested
    
    status = Column(
        Enum(ExportStatus, values_callable=lambda x: [e.value for e in x]),
        default=ExportStatus.PENDING,
        nullable=False
    )

    # Storage path to the generated ZIP file (in MinIO)
    result_path = Column(String, nullable=True)
    
    # File size in bytes (for UI display)
    file_size = Column(String, nullable=True)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Error message if failed
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ExportJob(id={self.id}, tenant={self.tenant_id}, status={self.status})>"
