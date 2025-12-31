"""
Base Connector
==============

Abstract interface for external data source connectors.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class ConnectorItem:
    """Represents an item fetched from a connector."""
    id: str
    title: str
    url: str
    updated_at: datetime
    content_type: str
    metadata: Dict[str, Any]


class BaseConnector(ABC):
    """
    Abstract base class for external data source connectors.
    
    Connectors must implement methods for authentication,
    fetching items (with incremental sync support), and content retrieval.
    """

    @abstractmethod
    async def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """
        Authenticate with the external service.
        
        Args:
            credentials: Service-specific credentials (API key, OAuth tokens, etc.)
            
        Returns:
            True if authentication successful.
        """
        pass

    @abstractmethod
    async def fetch_items(self, since: Optional[datetime] = None) -> AsyncIterator[ConnectorItem]:
        """
        Fetch items from the external service.
        
        Args:
            since: Only fetch items updated after this timestamp (for incremental sync).
            
        Yields:
            ConnectorItem for each item found.
        """
        pass

    @abstractmethod
    async def get_item_content(self, item_id: str) -> bytes:
        """
        Get the full content of a specific item.
        
        Args:
            item_id: ID of the item to retrieve.
            
        Returns:
            Raw content bytes.
        """
        pass

    @abstractmethod
    def get_connector_type(self) -> str:
        """
        Get the type identifier for this connector.
        
        Returns:
            Connector type string (e.g., 'zendesk', 'confluence').
        """
        pass

    async def test_connection(self) -> bool:
        """
        Test if the connection to the external service is working.
        
        Returns:
            True if connection is healthy.
        """
        try:
            # Default implementation - try to authenticate
            return await self.authenticate({})
        except Exception:
            return False
