"""
Chunk Model
===========

Database model for document chunks.
"""

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base

if TYPE_CHECKING:
    from src.core.models.document import Document


class EmbeddingStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class Chunk(Base):
    """
    Represents a semantically meaningful chunk of a document.
    """

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False) # 0-based index in the document

    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False) # Token count from tiktoken

    # Metadata includes: start_char, end_char, page_numbers, section_title
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}", nullable=False)

    embedding_status: Mapped[EmbeddingStatus] = mapped_column(
        SQLEnum(EmbeddingStatus), default=EmbeddingStatus.PENDING, nullable=False
    )

    # Relationship to parent document
    document: Mapped["Document"] = relationship("src.core.models.document.Document", back_populates="chunks")

    def __repr__(self):
        return f"<Chunk(id={self.id}, doc={self.document_id}, index={self.index})>"
