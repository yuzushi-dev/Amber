"""
Unit of Work
============

Provides transaction boundary management with explicit tenant scoping.
This consolidates session creation and ensures tenant context is always set.
"""

from collections.abc import Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork(Protocol):
    """Protocol defining the Unit of Work interface."""
    
    session: AsyncSession
    
    async def commit(self) -> None:
        """Commit the current transaction."""
        ...
    
    async def rollback(self) -> None:
        """Rollback the current transaction."""
        ...
    
    async def __aenter__(self) -> "UnitOfWork":
        """Enter the context manager."""
        ...
    
    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the context manager."""
        ...


class SqlAlchemyUnitOfWork:
    """
    SQLAlchemy implementation of Unit of Work.
    
    Manages transaction boundaries and injects tenant context for RLS.
    This is the ONLY place where tenant scoping should happen.
    """
    
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        tenant_id: str,
        is_super_admin: bool = False,
    ) -> None:
        """
        Initialize the Unit of Work.
        
        Args:
            session_factory: Factory function that creates AsyncSession instances.
            tenant_id: The tenant ID to scope all operations to.
            is_super_admin: If True, bypasses RLS restrictions.
        """
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._is_super_admin = is_super_admin
        self.session: AsyncSession | None = None
    
    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        """Enter the context manager and configure tenant scope."""
        self.session = self._session_factory()
        
        # Inject tenant scope explicitly via PostgreSQL session variables.
        # These are used by RLS policies to filter data.
        from sqlalchemy import text
        
        if self._tenant_id and not self._is_super_admin:
            await self.session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": self._tenant_id},
            )
        
        if self._is_super_admin:
            await self.session.execute(
                text("SELECT set_config('app.is_super_admin', 'true', false)")
            )
        
        return self
    
    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the context manager, committing or rolling back."""
        if not self.session:
            return
        
        if exc:
            await self.rollback()
        else:
            await self.commit()
        
        await self.session.close()
    
    async def commit(self) -> None:
        """Commit the current transaction."""
        if self.session:
            await self.session.commit()
    
    async def rollback(self) -> None:
        """Rollback the current transaction."""
        if self.session:
            await self.session.rollback()


# Type alias for UoW factory functions
UnitOfWorkFactory = Callable[[str, bool], SqlAlchemyUnitOfWork]
