from typing import Protocol


class UnitOfWork(Protocol):
    """
    Port for Atomic Transaction Management.
    """

    async def commit(self) -> None:
        """Commit the current transaction."""
        ...

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        ...
