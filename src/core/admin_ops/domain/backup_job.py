"""
Backup Job Model
================

Tracks background backup/restore jobs for system backup operations.
"""

import enum
from uuid import uuid4

from sqlalchemy import Column, DateTime, Enum, String, Text, Integer

from src.shared.kernel.models.base import Base, TimestampMixin


class BackupStatus(str, enum.Enum):
    """Status of a backup/restore job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackupScope(str, enum.Enum):
    """Scope of backup content."""
    USER_DATA = "user_data"      # Documents, conversations, memory
    FULL_SYSTEM = "full_system"  # + vectors, graph, configs


class RestoreMode(str, enum.Enum):
    """How to handle existing data during restore."""
    MERGE = "merge"      # Preserve existing data, add new
    REPLACE = "replace"  # Wipe and replace


class BackupJob(Base, TimestampMixin):
    """
    Tracks backup creation jobs.
    """
    __tablename__ = "backup_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=True)  # Who requested
    
    scope = Column(
        Enum(BackupScope, values_callable=lambda x: [e.value for e in x]),
        default=BackupScope.USER_DATA,
        nullable=False
    )
    
    status = Column(
        Enum(BackupStatus, values_callable=lambda x: [e.value for e in x]),
        default=BackupStatus.PENDING,
        nullable=False
    )

    # Storage path to the generated ZIP file (in MinIO)
    result_path = Column(String, nullable=True)
    
    # File size in bytes
    file_size = Column(Integer, nullable=True)
    
    # Progress percentage (0-100)
    progress = Column(Integer, default=0, nullable=False)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Error message if failed
    error_message = Column(Text, nullable=True)
    
    # Scheduled backup flag
    is_scheduled = Column(String, default="false", nullable=False)

    def __repr__(self) -> str:
        return f"<BackupJob(id={self.id}, scope={self.scope}, status={self.status})>"


class RestoreJob(Base, TimestampMixin):
    """
    Tracks restore jobs.
    """
    __tablename__ = "restore_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=True)
    
    # Source backup
    backup_job_id = Column(String, nullable=True)  # If restoring from existing backup
    upload_path = Column(String, nullable=True)     # If uploaded directly
    
    mode = Column(
        Enum(RestoreMode, values_callable=lambda x: [e.value for e in x]),
        default=RestoreMode.MERGE,
        nullable=False
    )
    
    status = Column(
        Enum(BackupStatus, values_callable=lambda x: [e.value for e in x]),
        default=BackupStatus.PENDING,
        nullable=False
    )
    
    # Progress percentage (0-100)
    progress = Column(Integer, default=0, nullable=False)
    
    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Error message if failed
    error_message = Column(Text, nullable=True)
    
    # Restore stats
    items_restored = Column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<RestoreJob(id={self.id}, mode={self.mode}, status={self.status})>"


class BackupSchedule(Base, TimestampMixin):
    """
    Configuration for scheduled backups.
    """
    __tablename__ = "backup_schedules"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, unique=True, nullable=False)
    
    enabled = Column(String, default="false", nullable=False)  # "true" or "false"
    
    # Schedule configuration
    frequency = Column(String, default="daily", nullable=False)  # daily, weekly
    time_utc = Column(String, default="02:00", nullable=False)   # HH:MM in UTC
    day_of_week = Column(Integer, nullable=True)  # 0-6 for weekly (0=Monday)
    
    scope = Column(
        Enum(BackupScope, values_callable=lambda x: [e.value for e in x]),
        default=BackupScope.USER_DATA,
        nullable=False
    )
    
    # Retention: how many backups to keep
    retention_count = Column(Integer, default=7, nullable=False)
    
    # Last run tracking
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_status = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<BackupSchedule(tenant={self.tenant_id}, enabled={self.enabled}, freq={self.frequency})>"
