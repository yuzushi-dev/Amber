"""
OpenTelemetry Tracer Logic
==========================

Sets up the distributed tracing system for the Amber system.
"""

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Global tracer instance
_tracer = None

# Try importing opentelemetry
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    logger.warning("OpenTelemetry not available. Tracing disabled.")

# -----------------------------------------------------------------------------
# Mocks for when OpenTelemetry is missing
# -----------------------------------------------------------------------------

class MockSpan:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass
    def record_exception(self, e): pass
    def set_status(self, status): pass

class MockTracer:
    def start_as_current_span(self, name):
        return MockSpan()

# -----------------------------------------------------------------------------
# Tracer Setup
# -----------------------------------------------------------------------------

def setup_tracer(service_name: str = "amber-rag") -> Any:
    """
    Sets up the OpenTelemetry TracerProvider and global tracer.
    """
    global _tracer

    if _tracer:
        return _tracer

    if not OPENTELEMETRY_AVAILABLE:
        _tracer = MockTracer()
        return _tracer

    # System resource information
    resource = Resource.create({"service.name": service_name})

    # Initialize Provider
    provider = TracerProvider(resource=resource)

    # Configure Console Exporter (for MVP/logs)
    console_exporter = ConsoleSpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(console_exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(__name__)

    logger.info(f"OpenTelemetry tracer initialized for service: {service_name}")
    return _tracer

def get_tracer() -> Any:
    """Returns the global tracer instance, initializing if necessary."""
    global _tracer
    if not _tracer:
        return setup_tracer()
    return _tracer

def trace_span(name: str | None = None):
    """
    Decorator to wrap a function in an OpenTelemetry span.

    Args:
        name: Override the span name. Defaults to function's name.
    """
    def decorator(func: Callable):
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            # Handle both MockTracer and real Tracer context managers
            ctx = tracer.start_as_current_span(span_name)

            # If using OTel, ctx is a context manager.
            # If mock, MockSpan is a context manager.
            with ctx as span:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if hasattr(span, "record_exception"):
                        span.record_exception(e)
                    # Handle OTel status setting if available
                    if OPENTELEMETRY_AVAILABLE and hasattr(span, "set_status"):
                        from opentelemetry import trace as ot_trace
                        span.set_status(ot_trace.Status(ot_trace.StatusCode.ERROR, str(e)))
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if hasattr(span, "record_exception"):
                        span.record_exception(e)
                    if OPENTELEMETRY_AVAILABLE and hasattr(span, "set_status"):
                        from opentelemetry import trace as ot_trace
                        span.set_status(ot_trace.Status(ot_trace.StatusCode.ERROR, str(e)))
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
