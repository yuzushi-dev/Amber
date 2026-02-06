"""
Database Session Management
===========================

Provides async database session utilities with lazy initialization.
The engine and session_maker are created on first access, not at import time.
This enables unit tests to import modules without requiring a database connection.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Lazy-initialized globals
_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None

# Database configuration holder
_db_config: dict = {}


def configure_database(database_url: str, pool_size: int = 5, max_overflow: int = 10) -> None:
    """Configure database connection parameters. Called by API layer on startup."""
    global _db_config
    _db_config = {
        "database_url": database_url,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
    }


def get_engine() -> AsyncEngine:
    """
    Get the async database engine, creating it on first access.

    Returns:
        AsyncEngine: The SQLAlchemy async engine.
    """
    global _engine
    if _engine is None:
        if not _db_config:
            raise RuntimeError("Database not configured. Call configure_database() first.")
        _engine = create_async_engine(
            _db_config["database_url"],
            echo=False,
            pool_pre_ping=True,
            pool_size=_db_config.get("pool_size", 5),
            max_overflow=_db_config.get("max_overflow", 10),
        )
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """
    Get the async session maker, creating it on first access.

    Returns:
        async_sessionmaker: Factory for creating database sessions.
    """
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


# Backward-compatible aliases (deprecated, use get_engine/get_session_maker)
# These are properties that lazily return the engine/session_maker
class _LazyEngine:
    """Lazy proxy for the engine to maintain backward compatibility."""

    def __getattr__(self, name):
        return getattr(get_engine(), name)

    def __call__(self, *args, **kwargs):
        return get_engine()(*args, **kwargs)


class _LazySessionMaker:
    """Lazy proxy for the session maker to maintain backward compatibility."""

    def __getattr__(self, name):
        return getattr(get_session_maker(), name)

    def __call__(self, *args, **kwargs):
        return get_session_maker()(*args, **kwargs)


# These proxies allow existing code using `engine` and `async_session_maker` to work
engine = _LazyEngine()
async_session_maker = _LazySessionMaker()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that yields a database session.

    Yields:
        AsyncSession: Database session that auto-closes.
    """
    async with get_session_maker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_database() -> None:
    """
    Dispose the engine and reset globals.
    Should be called on application shutdown.
    """
    global _engine, _async_session_maker
    try:
        if _engine:
            await _engine.dispose()
    finally:
        _engine = None
        _async_session_maker = None


def reset_engine() -> None:
    """
    Reset the engine and session maker. Useful for testing.
    """
    global _engine, _async_session_maker
    _engine = None
    _async_session_maker = None
