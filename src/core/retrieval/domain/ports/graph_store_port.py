from typing import Any, Protocol


class GraphStorePort(Protocol):
    """
    Port for Graph Store operations.
    """

    async def execute_read(
        self, query: str, parameters: dict[str, Any] = None
    ) -> list[dict[str, Any]]:
        """Execute a read query."""
        ...

    async def execute_write(
        self, query: str, parameters: dict[str, Any] = None
    ) -> list[dict[str, Any]]:
        """Execute a write query."""
        ...

    async def close(self) -> None:
        """Close connection."""
        ...
