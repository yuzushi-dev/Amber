"""
Usage Log Model
===============

Stores token usage and cost data for audit and billing purposes.
"""

from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, Float, Integer, String, JSON, DateTime
from sqlalchemy.sql import func
from src.core.models.base import Base, TimestampMixin

class UsageLog(Base, TimestampMixin):
    """
    Tracks LLM and Embedding usage across the system.
    """
    __tablename__ = "usage_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)
    request_id = Column(String, index=True)
    trace_id = Column(String, index=True)
    
    # Model info
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    operation = Column(String, nullable=False)  # 'generation', 'embedding', 'rerank'
    
    # Usage metrics
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    
    # Cost (USD)
    cost = Column(Float, default=0.0)
    
    # Metadata
    metadata_json = Column(JSON, default=dict)
    
    def __repr__(self) -> str:
        return f"<UsageLog(id={self.id}, model={self.model}, cost={self.cost})>"
