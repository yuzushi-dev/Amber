"""
Session Factory
================

Provides a shared session factory type for dependency injection.
"""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

# Type alias for session factory callables
SessionFactory = Callable[[], AsyncSession]
