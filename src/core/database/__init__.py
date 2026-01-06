"""
Database Module
===============

Database connection and session management.
Uses lazy initialization - engine is created on first use, not at import time.
"""

from src.core.database.session import (
    async_session_maker,
    # Backward-compatible aliases (proxies)
    engine,
    get_db,
    get_engine,
    get_session_maker,
    reset_engine,
)

__all__ = [
    "get_engine",
    "get_session_maker",
    "get_db",
    "reset_engine",
    # Legacy aliases
    "engine",
    "async_session_maker",
]
