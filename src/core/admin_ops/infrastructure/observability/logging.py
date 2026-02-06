"""
Structured Logging Configuration
================================

Provides JSON logging with correlation IDs and context propagation.
"""

import json
import logging
import sys
from typing import Any

from src.core.admin_ops.infrastructure.observability.tracer import get_current_request_id


class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings including context.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add Request ID / Correlation ID
        request_id = get_current_request_id()
        if request_id:
            log_obj["request_id"] = request_id

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add extra fields passed in 'extra' dict
        if hasattr(record, "props"):
            log_obj.update(record.props)

        return json.dumps(log_obj)


def configure_logging(log_level: str = "INFO", json_format: bool = True) -> None:
    """
    Configure root logger.

    Args:
        log_level: Logging level (DEBUG, INFO, etc.)
        json_format: Whether to output JSON or human-readable text.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)

    if json_format:
        formatter = JSONFormatter()
    else:
        # Fallback for local dev if preferred
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s] %(message)s")

    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # Silence some noisy libraries
    logging.getLogger("uvicorn.access").disabled = True  # We handle access logs via middleware
    logging.getLogger("multipart").setLevel(logging.WARNING)
