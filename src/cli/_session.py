"""Shared helpers for CLI commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    """Run an async coroutine from a sync Typer command."""
    return asyncio.run(coro)  # type: ignore[arg-type]


@asynccontextmanager
async def session_scope():
    """Yield a transactional async session backed by the configured database URL."""
    from src.api.config import settings

    url = settings.db.app_database_url or settings.db.database_url
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def with_session(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async with session_scope() as session:
        return await fn(session)
