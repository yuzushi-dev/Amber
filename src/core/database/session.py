"""
Database Session Management
===========================

Provides async database session utilities.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.api.config import settings


# Create async engine
engine = create_async_engine(
    settings.db.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.db.pool_size,
    max_overflow=settings.db.max_overflow,
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that yields a database session.
    
    Yields:
        AsyncSession: Database session that auto-closes.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
