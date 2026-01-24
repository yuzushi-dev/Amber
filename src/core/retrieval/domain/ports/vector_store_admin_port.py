from typing import Protocol


class VectorStoreAdminPort(Protocol):
    """Port for vector store administrative operations."""

    async def connect(self) -> None:
        """Connect to the vector store."""
        ...

    async def drop_collection(self) -> bool:
        """Drop the configured collection."""
        ...

    async def get_collection_dimensions(self) -> int | None:
        """Return the configured collection's vector dimensions, if available."""
        ...
