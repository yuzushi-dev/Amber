"""
Connector State Model
=====================

Tracks sync state for external connectors.
"""

from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, TimestampMixin


class ConnectorState(Base, TimestampMixin):
    """
    Tracks the state of external connector syncs.
    """

    __tablename__ = "connector_states"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    connector_type: Mapped[str] = mapped_column(String, nullable=False)  # zendesk, confluence, etc.
    
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_cursor: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)  # Pagination state
    
    status: Mapped[str] = mapped_column(String, default="idle", nullable=False)  # idle, syncing, error
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    def __repr__(self):
        return f"<ConnectorState(id={self.id}, type={self.connector_type}, status={self.status})>"
