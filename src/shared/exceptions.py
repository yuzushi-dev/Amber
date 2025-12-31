"""
Application Exceptions
======================

Structured exception hierarchy for the GraphRAG system.
"""

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
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


class UnauthorizedError(AppException):
    """Raised when authentication fails or is missing."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            code=ErrorCode.UNAUTHORIZED,
            message=message,
            status_code=401,
        )


class ForbiddenError(AppException):
    """Raised when the user lacks permission for an action."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            code=ErrorCode.FORBIDDEN,
            message=message,
            status_code=403,
        )


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


class PayloadTooLargeError(AppException):
    """Raised when upload exceeds size limit."""

    def __init__(self, max_size_mb: int, received_mb: float):
        super().__init__(
            code=ErrorCode.PAYLOAD_TOO_LARGE,
            message=f"Upload exceeds maximum size of {max_size_mb}MB",
            status_code=413,
            details={"max_size_mb": max_size_mb, "received_mb": received_mb},
        )


class ConcurrencyLimitError(AppException):
    """Raised when concurrency limit is exceeded."""

    def __init__(self, resource: str, limit: int):
        super().__init__(
            code=ErrorCode.CONCURRENCY_LIMIT,
            message=f"Maximum concurrent {resource} ({limit}) reached. Please wait.",
            status_code=429,
            details={"resource": resource, "limit": limit},
        )


class ConflictError(AppException):
    """Raised when there's a conflict with existing data."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            code=ErrorCode.CONFLICT,
            message=message,
            status_code=409,
            details=details,
        )


# =============================================================================
# 5xx Server Error Exceptions
# =============================================================================


class InternalError(AppException):
    """Raised for unexpected internal errors."""

    def __init__(self, message: str = "An unexpected error occurred"):
        super().__init__(
            code=ErrorCode.INTERNAL_ERROR,
            message=message,
            status_code=500,
        )


class ServiceUnavailableError(AppException):
    """Raised when the service is temporarily unavailable."""

    def __init__(self, message: str = "Service temporarily unavailable"):
        super().__init__(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=message,
            status_code=503,
        )


class DependencyError(AppException):
    """Raised when an external dependency fails."""

    def __init__(self, dependency: str, message: str | None = None):
        super().__init__(
            code=ErrorCode.DEPENDENCY_ERROR,
            message=message or f"Dependency unavailable: {dependency}",
            status_code=503,
            details={"dependency": dependency},
        )


class TimeoutError(AppException):
    """Raised when an operation times out."""

    def __init__(self, operation: str, timeout_seconds: float):
        super().__init__(
            code=ErrorCode.TIMEOUT,
            message=f"Operation timed out: {operation}",
            status_code=504,
            details={"operation": operation, "timeout_seconds": timeout_seconds},
        )
