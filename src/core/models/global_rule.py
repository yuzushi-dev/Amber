"""
Global Rule Model
=================

Stores global rules that are injected into the LLM system prompt.
These rules guide the AI's reasoning across all queries.
"""

from uuid import uuid4
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from src.core.models.base import Base, TimestampMixin


class GlobalRule(Base, TimestampMixin):
    """
    A global rule that guides AI reasoning.
    
    Rules are injected into the system prompt during generation.
    Examples:
    - "Carbonio requires at least one module to be installed."
    - "If only module 'Files' is installed, Carbonio will work."
    """
    __tablename__ = "global_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    
    # Rule content
    content = Column(Text, nullable=False)
    
    # Optional category for grouping (e.g., "Carbonio", "General")
    category = Column(String, nullable=True, index=True)
    
    # Priority/order for display and injection (lower = higher priority)
    priority = Column(Integer, default=100)
    
    # Active/inactive toggle
    is_active = Column(Boolean, default=True, index=True)
    
    # Source tracking (e.g., "manual", "file:rules.txt")
    source = Column(String, default="manual")

    def __repr__(self) -> str:
        return f"<GlobalRule(id={self.id}, content={self.content[:30]}...)>"
