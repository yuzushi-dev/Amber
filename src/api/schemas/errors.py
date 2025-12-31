"""
Error Response Schemas
======================

Pydantic models for consistent error responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error information."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    request_id: str | None = Field(None, description="Request ID for correlation")
    timestamp: datetime | None = Field(None, description="When the error occurred")
    details: dict[str, Any] | None = Field(None, description="Additional context")

    model_config = {"json_schema_extra": {"example": {
        "code": "NOT_FOUND",
        "message": "Document not found: doc_abc123",
        "request_id": "req_1234567890abcdef",
        "timestamp": "2024-01-15T10:30:00Z",
        "details": {"resource": "Document", "identifier": "doc_abc123"},
    }}}


class ErrorResponse(BaseModel):
    """Standard error response wrapper."""

    error: ErrorDetail

    model_config = {"json_schema_extra": {"example": {
        "error": {
            "code": "NOT_FOUND",
            "message": "Document not found: doc_abc123",
            "request_id": "req_1234567890abcdef",
            "timestamp": "2024-01-15T10:30:00Z",
        }
    }}}
