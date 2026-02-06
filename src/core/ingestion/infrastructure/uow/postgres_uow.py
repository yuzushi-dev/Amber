from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ingestion.domain.ports.unit_of_work import UnitOfWork


class PostgresUnitOfWork(UnitOfWork):
    """
    PostgreSQL implementation of UnitOfWork using SQLAlchemy.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        # Use simple rollback if transaction is active
        await self._session.rollback()
