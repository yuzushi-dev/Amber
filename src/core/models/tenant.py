"""
Tenant Model
============

Stores tenant-specific information and dynamic configuration (e.g., retrieval weights).
"""

from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, String
from sqlalchemy.orm import relationship

from src.core.models.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    """
    Represents a tenant in the system with associated configuration.
    """
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False)
    api_key_prefix = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)

    # Dynamic configuration (weights, model preferences, etc.)
    # Example: {"rerank_weight": 0.3, "vector_weight": 0.35, "graph_weight": 0.35}
    config = Column(JSON, default=dict)

    # Metadata
    metadata_json = Column(JSON, default=dict)

    # Many-to-Many relationship with ApiKey
    api_keys = relationship("ApiKey", secondary="api_key_tenants", back_populates="tenants", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name={self.name})>"
