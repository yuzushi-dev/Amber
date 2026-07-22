"""Shared helpers for CLI commands."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    """Run an async coroutine from a sync Typer command."""
    return asyncio.run(coro)  # type: ignore[arg-type]


@asynccontextmanager
async def session_scope() -> AsyncIterator[Any]:
    """Yield a transactional async session backed by the configured database URL.

    The yielded session is intentionally typed as ``Any``: CLI commands operate over
    legacy ``Column``-style ORM models, and annotating this as ``AsyncSession`` would
    surface pre-existing SQLAlchemy stub assignment errors across the CLI that are out
    of scope for this fix (the rest of the codebase handles the same debt via the mypy
    per-module override list).
    """
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
