"""
ApiKey Model
============

Stores API access keys with secure hashing.
"""

from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin


class ApiKey(Base, TimestampMixin):
    """
    Represents an API access key.
    
    Keys are stored as SHA-256 hashes. The raw key is never stored.
    """
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False, index=True)
    prefix = Column(String, nullable=False)  # e.g., "amber_"
    hashed_key = Column(String, nullable=False, index=True)  # SHA-256 hash
    last_chars = Column(String, nullable=False)  # Last 4 chars for display
    
    is_active = Column(Boolean, default=True, nullable=False)
    scopes = Column(JSON, default=list)  # List of permissions/scopes
    
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Many-to-Many relationship with Tenant
    tenants = relationship("Tenant", secondary="api_key_tenants", back_populates="api_keys", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ApiKey(name={self.name}, prefix={self.prefix}, active={self.is_active})>"


class ApiKeyTenant(Base):
    """
    Junction table for ApiKey <-> Tenant many-to-many relationship.
    Includes role-based access control per tenant.
    """
    __tablename__ = "api_key_tenants"

    api_key_id = Column(ForeignKey("api_keys.id", ondelete="CASCADE"), primary_key=True)
    tenant_id = Column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    
    # Role in this specific tenant context (e.g., "admin", "read", "write")
    role = Column(String, default="user", nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
