"""
Memory Models
=============

Database models for the Layered Memory System (User Facts and Conversation Summaries).
"""

from typing import Any

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, TimestampMixin


class UserFact(Base, TimestampMixin):
    """
    Represents a persistent fact learned about a user.
    Used for long-term memory retrieval.
    """
    __tablename__ = "user_facts"

    # Composite Primary Key: (tenant_id, user_id, fact_id) to ensure uniqueness per user context
    # However, for simplicity and standard practice, we use a global ID string or GUID.
    # Let's stick to valid string IDs provided by the application or UUIDs.

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5)

    # Flexible metadata (e.g. source_message_id, category, tags)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}", nullable=False)

    # Index for retrieval by user within a tenant
    __table_args__ = (
        Index("ix_user_facts_tenant_user", "tenant_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<UserFact(id={self.id}, user={self.user_id}, content={self.content[:20]}...)>"


class ConversationSummary(Base, TimestampMixin):
    """
    Represents a summarized past conversation.
    Used for mid-term memory to recall previous context.
    """
    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True) # Usually the session_id / conversation_id
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # Metadata (e.g. valid_from, valid_to, message_count)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}", nullable=False)

    __table_args__ = (
        Index("ix_conv_summaries_tenant_user_date", "tenant_id", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ConversationSummary(id={self.id}, title={self.title})>"
