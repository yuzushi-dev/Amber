"""
Request ID Middleware
=====================

Generates and propagates unique request IDs for tracing.
"""

import logging
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.shared.context import set_request_id
from src.shared.identifiers import RequestId

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request ID generation and propagation.

    - Generates a unique request ID for each request
    - Accepts client-provided IDs if valid UUIDs
    - Sets the ID in context for use throughout the request
    - Adds the ID to response headers
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request through request ID handling."""
        # Check for client-provided request ID
        client_id = request.headers.get(REQUEST_ID_HEADER)
        request_id: str

        if client_id:
            # Validate client ID (must be valid UUID)
            try:
                uuid.UUID(client_id)
                request_id = client_id
            except ValueError:
                # Invalid UUID, generate a new one
                request_id = f"req_{uuid.uuid4().hex}"
        else:
            # Generate new request ID
            request_id = f"req_{uuid.uuid4().hex}"

        # Set in context
        set_request_id(RequestId(request_id))

        # Store in request state
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers[REQUEST_ID_HEADER] = request_id

        return response
