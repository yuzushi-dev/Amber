"""
Exception Handlers
==================

Global exception handlers for consistent error responses.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from src.api.schemas.errors import ErrorDetail, ErrorResponse
from src.shared.context import get_request_id
from src.shared.exceptions import AppException, ErrorCode
from src.core.generation.domain.provider_models import RateLimitError

logger = logging.getLogger(__name__)


def _create_error_response(
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Create a standardized error response."""
    request_id = get_request_id()

    error = ErrorDetail(
        code=code,
        message=message,
        request_id=str(request_id) if request_id else None,
        timestamp=datetime.now(UTC),
        details=details,
    )

    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error).model_dump(mode="json"),
    )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Handle application-specific exceptions.

    Converts AppException to a structured JSON response.
    """
    logger.warning(
        f"Application error: {exc.code.value} - {exc.message}",
        extra={
            "request_id": get_request_id(),
            "path": request.url.path,
            "method": request.method,
            "error_code": exc.code.value,
        },
    )

    return _create_error_response(
        code=exc.code.value,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details if exc.details else None,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    Handle Pydantic validation errors.

    Converts validation errors to a user-friendly format.
    """
    # Format validation errors
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"],
        })

    logger.warning(
        f"Validation error: {len(errors)} errors",
        extra={
            "request_id": get_request_id(),
            "path": request.url.path,
            "method": request.method,
            "errors": errors,
        },
    )

    return _create_error_response(
        code=ErrorCode.VALIDATION_ERROR.value,
        message="Request validation failed",
        status_code=422,
        details={"errors": errors},
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Handle unhandled exceptions.

    Logs the full exception and returns a safe error message.
    Never exposes stack traces or internal details to clients.
    """
    request_id = get_request_id()

    # Log full exception for debugging
    logger.exception(
        f"Unhandled exception: {type(exc).__name__}: {exc}",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return _create_error_response(
        code=ErrorCode.INTERNAL_ERROR.value,
        message="An unexpected error occurred",
        status_code=500,
    )


async def rate_limit_exception_handler(
    request: Request,
    exc: RateLimitError,
) -> JSONResponse:
    """
    Handle provider rate limit errors.
    
    Converts provider RateLimitError to HTTP 429.
    """
    logger.warning(
        f"Rate limit exceeded: {exc}",
        extra={
            "request_id": get_request_id(),
            "path": request.url.path,
            "provider": exc.provider,
            "retry_after": exc.retry_after,
        },
    )

    details = {"provider": exc.provider}
    if exc.retry_after:
        details["retry_after"] = exc.retry_after

    return _create_error_response(
        code="rate_limit_exceeded",
        message=str(exc),
        status_code=429,
        details=details,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI app.

    Args:
        app: FastAPI application instance
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(RateLimitError, rate_limit_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
