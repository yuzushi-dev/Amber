"""
Timing Middleware
=================

Records and reports request timing information.
"""

import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.shared.context import get_request_id

logger = logging.getLogger(__name__)


class TimingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request timing.

    Records the time taken to process each request and
    adds timing information to response headers.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request through timing."""
        start_time = time.perf_counter()

        response = await call_next(request)

        # Calculate elapsed time
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Add timing header
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"

        # Log slow requests
        if elapsed_ms > 1000:  # > 1 second
            request_id = get_request_id() or "unknown"
            logger.warning(
                f"Slow request: {request.method} {request.url.path} "
                f"took {elapsed_ms:.2f}ms (request_id={request_id})"
            )

        return response
