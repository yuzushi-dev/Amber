"""
Audit Log Model
===============

Tracks administrative changes, configuration updates, and system events.
"""

from uuid import uuid4
from sqlalchemy import Column, String, JSON, DateTime
from datetime import datetime
from src.core.models.base import Base

class AuditLog(Base):
    """
    Audit log entry for system and configuration changes.
    """
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    actor = Column(String)  # Who made the change (e.g., user_id or "system")
    action = Column(String, nullable=False)  # e.g., "update_weights", "disable_tenant"
    
    # Details of the change
    target_type = Column(String)  # e.g., "tenant", "provider"
    target_id = Column(String)
    
    changes = Column(JSON)  # e.g., {"before": {...}, "after": {...}}
    
    metadata_json = Column(JSON, default=dict)
    
    def __repr__(self) -> str:
        return f"<AuditLog(action={self.action}, actor={self.actor}, timestamp={self.timestamp})>"
