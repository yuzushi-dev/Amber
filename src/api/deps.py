"""
API Dependencies
================

FastAPI dependency injection utilities.
"""

from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.config import settings

# Create async engine
_engine = create_async_engine(
    settings.db.database_url,
    echo=False,
    pool_pre_ping=True,
)

# Session factory
_async_session_maker = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that yields a database session.

    Yields:
        AsyncSession: Database session that auto-closes.
    """
    async with _async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def verify_admin(request: Request):
    """
    Dependency to verify admin privileges.
    """
    # Check permissions from request state (set by AuthMiddleware)
    permissions = getattr(request.state, "permissions", [])

    # In Phase 1/MVP, we might use a simple check or specific permission string
    if "admin" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
