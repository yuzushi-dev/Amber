"""
Structured Logging Configuration
================================

Unified logging for API and Worker using ``structlog``.

- **Dev / human**: Coloured, pretty-printed output via ``rich``.
- **Prod / json**: Machine-readable JSON lines.

Environment variables
~~~~~~~~~~~~~~~~~~~~~
- ``LOG_LEVEL``  – DEBUG | INFO | WARNING | ERROR | CRITICAL  (default: INFO)
- ``LOG_FORMAT`` – ``json`` | ``human``  (default: ``json``)
- ``AMBER_RUNTIME`` – When set to ``docker`` the format defaults to ``json``.

All standard-library loggers are automatically routed through structlog
so that *every* log line – including third-party libraries – obeys the
configured level and format.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog

from src.core.admin_ops.infrastructure.observability.tracer import get_current_request_id


# -------------------------------------------------------------------------
# Noisy loggers that should be silenced unless the user *really* wants them
# -------------------------------------------------------------------------
_NOISY_LOGGERS: dict[str, int] = {
    # HTTP clients
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    # Database drivers
    "neo4j": logging.WARNING,
    "neo4j.io": logging.WARNING,
    "neo4j.pool": logging.WARNING,
    "pymilvus": logging.WARNING,
    "asyncpg": logging.WARNING,
    # OpenTelemetry (the biggest noise source in worker logs)
    "opentelemetry": logging.WARNING,
    "opentelemetry.sdk": logging.WARNING,
    "opentelemetry.exporter": logging.WARNING,
    "opentelemetry.trace": logging.WARNING,
    # Web server internals
    "uvicorn.access": logging.WARNING,
    "uvicorn.error": logging.WARNING,
    "multipart": logging.WARNING,
    "multipart.multipart": logging.WARNING,
    # Celery internals (keep only warnings+)
    "celery.worker.strategy": logging.WARNING,
    "celery.app.trace": logging.WARNING,
    # ML / embedding model loaders
    "sentence_transformers": logging.WARNING,
    "transformers": logging.WARNING,
    "huggingface_hub": logging.WARNING,
    "torch": logging.WARNING,
    "matplotlib": logging.WARNING,
    "matplotlib.font_manager": logging.WARNING,
}


# -------------------------------------------------------------------------
# Custom structlog processor: inject request_id if available
# -------------------------------------------------------------------------
def _add_request_id(
    logger: logging.Logger,  # noqa: ARG001
    method_name: str,  # noqa: ARG001
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Inject the current request/correlation ID when available."""
    request_id = get_current_request_id()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------
def configure_logging(
    log_level: str = "INFO",
    json_format: bool | None = None,
) -> None:
    """Configure application-wide structured logging.

    Parameters
    ----------
    log_level:
        Minimum severity.  Overridden by ``LOG_LEVEL`` env var if set.
    json_format:
        ``True`` → JSON lines, ``False`` → coloured console output.
        When *None* the function auto-detects from ``LOG_FORMAT`` /
        ``AMBER_RUNTIME`` env vars.
    """

    # --- resolve effective level ----------------------------------------
    level_name = os.getenv("LOG_LEVEL", log_level).upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    # --- resolve format -------------------------------------------------
    if json_format is None:
        fmt_env = os.getenv("LOG_FORMAT", "").lower()
        runtime = os.getenv("AMBER_RUNTIME", "").lower()
        if fmt_env == "human":
            json_format = False
        elif fmt_env == "json":
            json_format = True
        else:
            # Default: JSON in Docker, human otherwise
            json_format = runtime == "docker"

    # --- shared processors (run in every log event) ---------------------
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _add_request_id,
    ]

    if json_format:
        # For JSON we format exceptions as strings inside the JSON object
        shared_processors.append(
            structlog.processors.format_exc_info,
        )

    # --- structlog configuration ----------------------------------------
    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare the event dict for stdlib's ProcessorFormatter
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- stdlib root logger ---------------------------------------------
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove any pre-existing handlers to avoid duplicate lines
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Choose renderer
    if json_format:
        renderer = structlog.processors.JSONRenderer()
    else:
        try:
            import rich  # noqa: F401

            renderer = structlog.dev.ConsoleRenderer(colors=True)
        except ImportError:
            renderer = structlog.dev.ConsoleRenderer(colors=False)

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # --- silence noisy libraries ----------------------------------------
    for logger_name, level in _NOISY_LOGGERS.items():
        noisy = logging.getLogger(logger_name)
        # Only raise the level – never lower it below the user's choice
        effective = max(level, numeric_level)
        noisy.setLevel(effective)

    # Completely disable uvicorn access logs (we have our own middleware)
    logging.getLogger("uvicorn.access").disabled = True
