"""
Feedback Model
==============

Stores user feedback (scores, comments, corrections) for RAG answers.
"""

from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, Float, String

from src.core.models.base import Base, TimestampMixin


class Feedback(Base, TimestampMixin):
    """
    User feedback for a specific RAG response.
    """
    __tablename__ = "feedbacks"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String, index=True, nullable=False)
    request_id = Column(String, index=True, nullable=False)

    # Feedback metrics
    score = Column(Float)  # 1.0 for positive, 0.0 for negative (or custom range)
    is_positive = Column(Boolean, default=True)
    comment = Column(String)

    # Correction data (if provided)
    correction = Column(String)

    # Metadata (trace_id, model, query_text, etc.)
    metadata_json = Column(JSON, default=dict)

    def __repr__(self) -> str:
        return f"<Feedback(id={self.id}, request_id={self.request_id}, score={self.score})>"
