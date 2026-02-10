"""
Query Models
============

Internal models for structured query analysis and execution tracing.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class StructuredQuery(BaseModel):
    """A query that has been parsed for filters and metadata."""

    original_query: str = Field(..., description="The untouched user query")
    cleaned_query: str = Field(..., description="Query text with filters removed")

    # Extracted filters
    document_ids: list[str] | None = Field(default_factory=list)
    tags: list[str] | None = Field(default_factory=list)
    date_after: datetime | None = None
    date_before: datetime | None = None

    # Metadata
    domain: str | None = Field(None, description="Inferred domain (technical, legal, etc.)")
    intent: str | None = Field(None, description="Inferred intent (summary, fact, etc.)")


class QueryTrace(BaseModel):
    """Detailed record of a query's lifecycle."""

    query_id: str
    steps: list[dict[str, Any]] = Field(default_factory=list)

    def add_step(self, name: str, duration_ms: float, details: dict[str, Any] | None = None):
        """Add a step to the trace."""
        self.steps.append(
            {
                "step": name,
                "duration_ms": round(duration_ms, 2),
                "details": details or {},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
