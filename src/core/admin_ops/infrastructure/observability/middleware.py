"""
Observability Middleware
=========================

Middleware for request tracing and structured logging.
"""

import logging
import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.admin_ops.infrastructure.observability.tracer import (
    reset_current_request_id,
    set_current_request_id,
)

logger = structlog.stdlib.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique ID to each request and sets it in the logging context.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check if client sent a request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Set context var (for legacy tracer)
        token = set_current_request_id(request_id)

        # Also bind into structlog contextvars so all downstream logs include it
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            response = await call_next(request)
            # Add header to response
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_current_request_id(token)
            structlog.contextvars.clear_contextvars()


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request with structured info (latency, status, path).
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()

        path = request.url.path
        method = request.method

        # Skip health checks to avoid log noise
        if path.endswith("/health") or path.endswith("/ready"):
            return await call_next(request)

        try:
            response = await call_next(request)

            latency = (time.perf_counter() - start_time) * 1000

            log_kw = dict(
                method=method,
                path=path,
                status_code=response.status_code,
                latency_ms=round(latency, 2),
                ip=request.client.host if request.client else None,
            )

            # Log level depends on status code
            if response.status_code >= 500:
                logger.error("request_failed", **log_kw)
            elif response.status_code >= 400:
                logger.warning("request_bad_input", **log_kw)
            else:
                logger.info("request_processed", **log_kw)

            return response

        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000
            logger.error(
                "request_exception",
                method=method,
                path=path,
                status_code=500,
                latency_ms=round(latency, 2),
                exc_info=True,
            )
            raise e
