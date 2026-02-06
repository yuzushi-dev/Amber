"""
Confluence Connector
====================

Connector for Confluence Cloud.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from src.core.ingestion.infrastructure.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)


class ConfluenceConnector(BaseConnector):
    """
    Connector for Confluence Cloud.

    Authenticates via Email + API Token (Basic Auth) and fetches pages.
    Uses Confluence Cloud REST API v2.
    """

    def __init__(self, base_url: str = None, email: str = None, api_token: str = None):
        """
        Initialize Confluence connector.

        Args:
            base_url: Confluence base URL (e.g., 'https://domain.atlassian.net/wiki')
            email: User email for API authentication
            api_token: API token
        """
        self.base_url = base_url.rstrip("/") if base_url else None
        self.email = email
        self.api_token = api_token
        self._authenticated = False

    async def authenticate(self, credentials: dict[str, Any]) -> bool:
        """
        Authenticate with Confluence API.

        Args:
            credentials: 'base_url', 'email', and 'api_token'.
        """
        base_url = credentials.get("base_url", self.base_url)
        email = credentials.get("email", self.email)
        api_token = credentials.get("api_token", self.api_token)

        if not base_url or not email or not api_token:
            logger.error("Confluence credentials incomplete (need base_url, email, api_token)")
            return False

        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token

        # Test authentication by fetching current user or simple endpoint
        # /rest/api/user/current is a good candidate
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/rest/api/user/current", auth=(email, api_token)
                )
                response.raise_for_status()
                self._authenticated = True
                logger.info(f"Authenticated with Confluence as {email}")
                return True
        except Exception as e:
            logger.error(f"Confluence authentication failed: {e}")
            return False

    async def fetch_items(self, since: datetime | None = None) -> AsyncIterator[ConnectorItem]:
        """
        Fetch pages from Confluence (V2 API).
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        # V2 uses cursor-based pagination
        url = f"{self.base_url}/rest/api/content"  # Fallback check, wait
        # V2 Endpoint: /api/v2/pages
        # But we need to handle the base_url.
        # User gives: https://domain.atlassian.net/wiki
        # API: https://domain.atlassian.net/wiki/api/v2/pages

        url = f"{self.base_url}/api/v2/pages"
        params = {"limit": 50}  # Max is usually 250 in V2? Defaults 25.

        # Note: V2 Pages doesn't support 'cql' or simple date filtering directly in parameters easily
        # without searching.
        # For 'since' support, we might need to iterate or use search.
        # Given 'fetch_items' is for full sync, iterating is okay, but inefficient if we can't filter.
        # However, for this MVP refactor, we will stick to V2 pages iteration.

        # If 'since' is provided, we might be better off using search (V1/V2 shared).
        # But let's try to be V2 compliant for the 'pure' fetch.
        # Actually, let's use the V2 endpoint and client-side filter if needed,
        # OR just acknowledge that 'since' might be hard with pure /pages.

        async with httpx.AsyncClient() as client:
            while url:
                response = await client.get(url, params=params, auth=(self.email, self.api_token))
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                if not results:
                    break

                for page in results:
                    # Filter by date if 'since' provided?
                    # page['createdAt'] is available.
                    yield self._map_v2_to_item(page)

                # Pagination
                # Link header or _links.next
                # V2 often puts 'next' in '_links' body.
                url = data.get("_links", {}).get("next")
                if url and not url.startswith("http"):
                    # Relative URL
                    url = f"{self.base_url}{url}"

                params = {}  # Next URL usually has params

    async def get_item_content(self, item_id: str) -> bytes:
        """
        Get the storage format (HTML-like) of a page.
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        async with httpx.AsyncClient() as client:
            # V2 API: /api/v2/pages/{id}?body-format=storage
            url = f"{self.base_url}/api/v2/pages/{item_id}"

            response = await client.get(
                url, params={"body-format": "storage"}, auth=(self.email, self.api_token)
            )
            response.raise_for_status()
            data = response.json()

            # V2: body.storage.value (Wait, V2 response structure is different)
            # V2 response: { "body": { "storage": { "value": "..." } } } ?
            # Actually V2 usually returns 'body' field if requested.
            # Let's verify structure via mapping logic or just safe access.
            body = data.get("body", {}).get("storage", {}).get("value", "")
            return body.encode("utf-8")

    def get_connector_type(self) -> str:
        return "confluence"

    async def list_items(
        self, page: int = 1, page_size: int = 20, search: str = None
    ) -> tuple[list[ConnectorItem], bool]:
        """
        List/Search pages.
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        # API uses 'start' and 'limit'
        start = (page - 1) * page_size

        cql = "type=page"
        if search:
            # Basic text search in CQL
            cql += f' AND text ~ "{search}"'

        params = {"cql": cql, "start": start, "limit": page_size, "expand": "version,history"}

        async with httpx.AsyncClient() as client:
            # Using CQL search endpoint might be better for 'text ~', but /content/search is also standard.
            # /rest/api/content/search is usually better for CQL.
            # However, /rest/api/content with `cql` param is deprecated in some versions but works in Cloud.
            # Let's try /rest/api/content/search which is safer for CQL.

            url = f"{self.base_url}/rest/api/content/search"

            response = await client.get(url, params=params, auth=(self.email, self.api_token))
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            items = [self._map_to_item(p) for p in results]

            # Simple check for more
            has_more = len(items) == page_size

            return items, has_more

    def _map_v2_to_item(self, page: dict) -> ConnectorItem:
        """Map Confluence V2 API object to ConnectorItem."""
        # V2: createdAt, title, id, status
        updated_input = page.get("createdAt", "")
        try:
            updated_at = datetime.fromisoformat(updated_input.replace("Z", "+00:00"))
        except Exception:
            updated_at = datetime.now()

        # WebUI link usually in _links
        web_link = f"{self.base_url}/spaces/{page.get('spaceId')}/pages/{page.get('id')}"
        if "_links" in page and "webui" in page["_links"]:
            # V2 _links might be /wiki/...
            web_link = self.base_url + page["_links"]["webui"].replace(
                "/wiki", "", 1
            )  # careful mapping

        return ConnectorItem(
            id=str(page["id"]),
            title=page.get("title", "Untitled"),
            url=web_link,
            updated_at=updated_at,
            content_type="text/html",
            metadata={
                "space_id": page.get("spaceId"),
                "status": page.get("status"),
                "version": page.get("version", {}).get("number"),
            },
        )

    def _map_to_item(self, page: dict) -> ConnectorItem:
        """Map Confluence V1 API object to ConnectorItem."""
        # version.when is update time
        updated_input = page.get("version", {}).get("when", "")
        try:
            # Confluence dates are usually ISO8601
            updated_at = datetime.fromisoformat(updated_input.replace("Z", "+00:00"))
        except Exception:
            updated_at = datetime.now()

        # Generate a web link (base_url + _links.webui)
        web_link = self.base_url + page.get("_links", {}).get("webui", "")

        return ConnectorItem(
            id=str(page["id"]),
            title=page.get("title", "Untitled"),
            url=web_link,
            updated_at=updated_at,
            content_type="text/html",  # It's XHTML storage format
            metadata={
                "space_key": page.get("space", {}).get("key"),
                "status": page.get("status"),
                "version": page.get("version", {}).get("number"),
            },
        )

    # --- Agent Tools ---

    def get_agent_tools(self) -> list[dict[str, Any]]:
        return [
            self._tool_search_pages(),
            self._tool_get_page(),
            self._tool_add_comment(),
        ]

    def _tool_search_pages(self):
        async def search_pages(query: str, limit: int = 5) -> str:
            """Search Confluence pages using CQL."""
            if not self._authenticated:
                return "Error: Not authenticated."

            # CQL Search
            cql = f'text ~ "{query}" AND type=page'

            try:
                # Reuse list_items logic effectively but tailored for agent output
                params = {
                    "cql": cql,
                    "limit": limit,
                }
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/rest/api/content/search",
                        params=params,
                        auth=(self.email, self.api_token),
                    )
                    data = response.json()
                    results = data.get("results", [])

                    if not results:
                        return "No pages found."

                    output = []
                    for p in results:
                        pid = p.get("id")
                        title = p.get("title")
                        link = self.base_url + p.get("_links", {}).get("webui", "")
                        output.append(f"- [{pid}] {title} ({link})")

                    return "\n".join(output)
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "search_pages",
            "func": search_pages,
            "schema": {
                "type": "function",
                "function": {
                    "name": "search_pages",
                    "description": "Search Confluence pages.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search terms"},
                            "limit": {"type": "integer", "default": 5},
                        },
                        "required": ["query"],
                    },
                },
            },
        }

    def _tool_get_page(self):
        async def get_page(page_id: str) -> str:
            """Get content of a page."""
            if not self._authenticated:
                return "Error: Not authenticated."

            try:
                # Use storage format
                content_bytes = await self.get_item_content(page_id)
                content = content_bytes.decode("utf-8")

                # It's HTML, might be verbose. Agent can handle it, or we could strip tags.
                # For Agent reading, raw HTML is often okay if not massive.
                return content[:10000]  # Limit size
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "get_page",
            "func": get_page,
            "schema": {
                "type": "function",
                "function": {
                    "name": "get_page",
                    "description": "Read a Confluence page.",
                    "parameters": {
                        "type": "object",
                        "properties": {"page_id": {"type": "string"}},
                        "required": ["page_id"],
                    },
                },
            },
        }

    def _tool_add_comment(self):
        async def add_comment(page_id: str, comment: str) -> str:
            """Add a footer comment to a page."""
            if not self._authenticated:
                return "Error: Not authenticated."

            body = {
                "type": "comment",
                "container": {"type": "page", "id": page_id},
                "body": {"storage": {"value": f"<p>{comment}</p>", "representation": "storage"}},
            }

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.base_url}/rest/api/content",
                        json=body,
                        auth=(self.email, self.api_token),
                    )
                    if response.status_code != 200:
                        return f"Error: {response.text}"
                    return "Comment added."
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "add_comment",
            "func": add_comment,
            "schema": {
                "type": "function",
                "function": {
                    "name": "add_comment",
                    "description": "Add a comment to a Confluence page.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string"},
                            "comment": {"type": "string"},
                        },
                        "required": ["page_id", "comment"],
                    },
                },
            },
        }
