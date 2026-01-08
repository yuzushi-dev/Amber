"""
Folder Model
============

Database model for document folders.
"""

from typing import TYPE_CHECKING, List

from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.core.models.document import Document

class Folder(Base, TimestampMixin):
    """
    Represents a folder for organizing documents.
    """

    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    
    # Relationship to documents
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="folder")

    def __repr__(self):
        return f"<Folder(id={self.id}, name={self.name})>"
