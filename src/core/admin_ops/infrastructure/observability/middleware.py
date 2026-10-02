"""
Observability Middleware
=========================

Middleware for request tracing and structured logging.
"""

import time
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.stdlib.get_logger(__name__)


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

            log_kw = {
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "latency_ms": round(latency, 2),
                "ip": request.client.host if request.client else None,
                "key_name": getattr(request.state, "api_key_name", None),
                "key_prefix": getattr(request.state, "api_key_prefix", None),
                "tenant_id": getattr(request.state, "tenant_id", None),
            }

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
