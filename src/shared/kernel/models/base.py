"""
Base Model
==========

SQLAlchemy declarative base and common mixins.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def _utcnow() -> datetime:
    # Column is TIMESTAMP WITHOUT TIME ZONE — return naive UTC
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    """Mixin to add created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
