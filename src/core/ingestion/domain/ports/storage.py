from typing import Protocol, Any


class StoragePort(Protocol):
    """Port for object storage operations."""

    def upload_file(
        self, object_name: str, data: Any, length: int, content_type: str
    ) -> None:
        """Upload a file to storage."""
        ...

    def get_file(self, object_name: str) -> bytes:
        """Get file content from storage."""
        ...

    def delete_file(self, object_name: str) -> None:
        """Delete a file from storage."""
        ...
