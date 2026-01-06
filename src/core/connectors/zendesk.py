"""
Zendesk Connector
=================

Connector for Zendesk Help Center articles.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from src.core.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)


class ZendeskConnector(BaseConnector):
    """
    Connector for Zendesk Help Center.

    Authenticates via API token and fetches articles.
    Supports incremental sync using updated_at filtering.
    """

    def __init__(self, subdomain: str, email: str = None, api_token: str = None):
        """
        Initialize Zendesk connector.

        Args:
            subdomain: Zendesk subdomain (e.g., 'mycompany' for mycompany.zendesk.com)
            email: Admin email for API authentication
            api_token: API token
        """
        self.subdomain = subdomain
        self.email = email
        self.api_token = api_token
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        self._authenticated = False

    async def authenticate(self, credentials: dict[str, Any]) -> bool:
        """
        Authenticate with Zendesk API.

        Args:
            credentials: Optional override credentials with 'email' and 'api_token'.
        """
        email = credentials.get("email", self.email)
        api_token = credentials.get("api_token", self.api_token)

        if not email or not api_token:
            logger.error("Zendesk credentials not provided")
            return False

        self.email = email
        self.api_token = api_token

        # Test authentication
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/users/me.json",
                    auth=(f"{email}/token", api_token)
                )
                response.raise_for_status()
                self._authenticated = True
                logger.info(f"Authenticated with Zendesk as {email}")
                return True
        except Exception as e:
            logger.error(f"Zendesk authentication failed: {e}")
            return False

    async def fetch_items(self, since: datetime | None = None) -> AsyncIterator[ConnectorItem]:
        """
        Fetch articles from Zendesk Help Center.

        Args:
            since: Only fetch articles updated after this timestamp.
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        url = f"{self.base_url}/help_center/articles.json"
        params = {"per_page": 100}

        if since:
            params["updated_after"] = since.isoformat()

        async with httpx.AsyncClient() as client:
            while url:
                response = await client.get(
                    url,
                    params=params,
                    auth=(f"{self.email}/token", self.api_token)
                )
                response.raise_for_status()
                data = response.json()

                for article in data.get("articles", []):
                    yield ConnectorItem(
                        id=str(article["id"]),
                        title=article.get("name", "Untitled"),
                        url=article.get("html_url", ""),
                        updated_at=datetime.fromisoformat(article["updated_at"].replace("Z", "+00:00")),
                        content_type="text/html",
                        metadata={
                            "section_id": article.get("section_id"),
                            "author_id": article.get("author_id"),
                            "draft": article.get("draft", False),
                            "promoted": article.get("promoted", False),
                            "vote_sum": article.get("vote_sum", 0),
                        }
                    )

                # Handle pagination
                url = data.get("next_page")
                params = {}  # Next page URL includes params

    async def get_item_content(self, item_id: str) -> bytes:
        """
        Get the HTML content of a specific article.
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/help_center/articles/{item_id}.json",
                auth=(f"{self.email}/token", self.api_token)
            )
            response.raise_for_status()
            data = response.json()

            body = data.get("article", {}).get("body", "")
            return body.encode("utf-8")

    def get_connector_type(self) -> str:
        return "zendesk"
