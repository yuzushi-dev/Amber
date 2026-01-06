"""
Flag Model
==========

Stores analyst-reported data quality issues for curation queue (SME loop).
"""

import enum
from uuid import uuid4

from sqlalchemy import JSON, Column, String
from sqlalchemy import Enum as SQLEnum

from src.core.models.base import Base, TimestampMixin


class FlagType(str, enum.Enum):
    """Types of flags that can be reported."""
    WRONG_FACT = "wrong_fact"
    BAD_LINK = "bad_link"
    WRONG_ENTITY = "wrong_entity"
    MISSING_ENTITY = "missing_entity"
    DUPLICATE_ENTITY = "duplicate_entity"
    MERGE_SUGGESTION = "merge_suggestion"
    OTHER = "other"


class FlagStatus(str, enum.Enum):
    """Flag resolution status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MERGED = "merged"


class Flag(Base, TimestampMixin):
    """
    Analyst-reported flag for data quality issues.

    Part of the SME (Subject Matter Expert) loop where analysts
    flag incorrect facts, entities, or relationships during their work.
    """
    __tablename__ = "flags"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)

    # Flag metadata
    # Use values_callable to ensure lowercase values match PostgreSQL enum
    type = Column(SQLEnum(FlagType, values_callable=lambda x: [e.value for e in x]), nullable=False, index=True)
    status = Column(SQLEnum(FlagStatus, values_callable=lambda x: [e.value for e in x]), default=FlagStatus.PENDING, index=True)

    # Reporter info
    reported_by = Column(String, nullable=False)  # User ID or username

    # Target of the flag
    target_type = Column(String, nullable=False)  # 'chunk', 'entity', 'relationship'
    target_id = Column(String, nullable=False, index=True)

    # Context and details
    comment = Column(String)  # User's explanation
    context = Column(JSON, default=dict)  # Query, chunk text, entity names, etc.

    # Resolution info
    resolved_by = Column(String)
    resolved_at = Column(String)  # ISO timestamp
    resolution_notes = Column(String)
    merge_target_id = Column(String)  # For merge operations

    def __repr__(self) -> str:
        return f"<Flag(id={self.id}, type={self.type}, status={self.status})>"

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "type": self.type.value if isinstance(self.type, enum.Enum) else self.type,
            "status": self.status.value if isinstance(self.status, enum.Enum) else self.status,
            "reported_by": self.reported_by,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "comment": self.comment,
            "context": self.context or {},
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
            "merge_target_id": self.merge_target_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
