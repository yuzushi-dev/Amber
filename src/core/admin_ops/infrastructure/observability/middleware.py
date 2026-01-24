"""
Observability Middleware
=========================

Middleware for request tracing and structured logging.
"""

import time
import uuid
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.admin_ops.infrastructure.observability.tracer import set_current_request_id, reset_current_request_id

logger = logging.getLogger(__name__)

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique ID to each request and sets it in the logging context.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check if client sent a request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        
        # Set context var
        token = set_current_request_id(request_id)
        
        try:
            response = await call_next(request)
            # Add header to response
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_current_request_id(token)


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
            
            log_data = {
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "latency_ms": round(latency, 2),
                "ip": request.client.host if request.client else None
            }
            
            # Log level depends on status code
            if response.status_code >= 500:
                logger.error("Request failed", extra={"props": log_data})
            elif response.status_code >= 400:
                logger.warning("Request bad input", extra={"props": log_data})
            else:
                logger.info("Request processed", extra={"props": log_data})
                
            return response
            
        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000
            logger.error(f"Request exception: {str(e)}", extra={
                "props": {
                    "method": method,
                    "path": path,
                    "status_code": 500,
                    "latency_ms": round(latency, 2)
                }
            })
            raise e
