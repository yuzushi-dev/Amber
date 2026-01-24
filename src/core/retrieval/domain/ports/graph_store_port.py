from typing import Protocol, Any, Dict, List

class GraphStorePort(Protocol):
    """
    Port for Graph Store operations.
    """
    
    async def execute_read(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Execute a read query."""
        ...

    async def execute_write(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Execute a write query."""
        ...
        
    async def close(self) -> None:
        """Close connection."""
        ...
