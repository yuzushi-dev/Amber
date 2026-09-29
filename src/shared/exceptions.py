"""
Application Exceptions
======================

Structured exception hierarchy for the GraphRAG system.
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Standard error codes for API responses."""

    # 4xx Client Errors
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
    CONFLICT = "CONFLICT"
    UNPROCESSABLE_ENTITY = "UNPROCESSABLE_ENTITY"

    # 5xx Server Errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    TIMEOUT = "TIMEOUT"


class AppException(Exception):
    """
    Base exception for application errors.

    All application-specific exceptions should inherit from this.
    Provides structured error information for consistent API responses.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        """
        Initialize the exception.

        Args:
            code: Machine-readable error code
            message: Human-readable error message
            status_code: HTTP status code
            details: Additional error details
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API response."""
        result = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


# =============================================================================
# 4xx Client Error Exceptions
# =============================================================================


class NotFoundError(AppException):
    """Raised when a requested resource doesn't exist."""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=f"{resource} not found: {identifier}",
            status_code=404,
            details={"resource": resource, "identifier": identifier},
        )


class ValidationError(AppException):
    """Raised when request validation fails."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            status_code=422,
            details={"errors": errors} if errors else None,
        )


class RateLimitError(AppException):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: int):
        super().__init__(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message=f"Too many requests. Retry after {retry_after} seconds.",
            status_code=429,
            details={"retry_after": retry_after},
        )


# =============================================================================
# 5xx Server Error Exceptions
# =============================================================================


class TimeoutError(AppException):
    """Raised when an operation times out."""

    def __init__(self, operation: str, timeout_seconds: float):
        super().__init__(
            code=ErrorCode.TIMEOUT,
            message=f"Operation timed out: {operation}",
            status_code=504,
            details={"operation": operation, "timeout_seconds": timeout_seconds},
        )
