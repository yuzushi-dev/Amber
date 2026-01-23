from typing import Protocol


class GraphPort(Protocol):
    """Port for graph database operations."""

    async def execute_write(self, query: str, parameters: dict) -> None:
        """Execute a write query."""
        ...

    async def execute_read(self, query: str, parameters: dict) -> list[dict]:
        """Execute a read query."""
        ...
