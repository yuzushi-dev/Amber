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

    async def list_items(self, page: int = 1, page_size: int = 20, search: str = None) -> tuple[list[ConnectorItem], bool]:
        """
        List items from Zendesk.
        """
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        params = {"page": page, "per_page": page_size}
        
        if search:
            url = f"{self.base_url}/help_center/articles/search.json"
            params["query"] = search
        else:
            url = f"{self.base_url}/help_center/articles.json"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                params=params,
                auth=(f"{self.email}/token", self.api_token)
            )
            response.raise_for_status()
            data = response.json()

            items = []
            # 'results' for search, 'articles' for list
            raw_items = data.get("results", []) if search else data.get("articles", [])

            for article in raw_items:
                # Basic validation to ensure we have an ID and Title
                if "id" not in article:
                    continue
                    
                items.append(ConnectorItem(
                    id=str(article["id"]),
                    title=article.get("name", article.get("title", "Untitled")),
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
                ))

            # Check for next page
            has_more = bool(data.get("next_page"))
            return items, has_more

    # --- Agent Tools ---

    def get_agent_tools(self) -> list[dict[str, Any]]:
        return [
            self._tool_get_tickets(),
            self._tool_get_ticket(),
            self._tool_create_ticket(),
            self._tool_update_ticket(),
            self._tool_get_ticket_comments(),
            self._tool_create_ticket_comment(),
        ]

    def _tool_get_tickets(self):
        async def get_tickets(limit: int = 10, status: str = None, priority: str = None) -> str:
            """List recent Zendesk tickets."""
            if not self._authenticated:
                return "Error: Connector not authenticated."

            params = {"per_page": limit, "sort_by": "updated_at", "sort_order": "desc"}
            # Basic basic filtering via search API is often better, but let's try standard list first
            # "GET /api/v2/tickets.json" lists all. For filtering we might need search.
            
            url = f"{self.base_url}/tickets.json"
            
            # If filters provided, use Search API instead
            if status or priority:
                url = f"{self.base_url}/search.json"
                query_parts = ["type:ticket"]
                if status: query_parts.append(f"status:{status}")
                if priority: query_parts.append(f"priority:{priority}")
                params["query"] = " ".join(query_parts)
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        url, 
                        params=params, 
                        auth=(f"{self.email}/token", self.api_token)
                    )
                    if response.status_code != 200:
                        return f"Error: HTTP {response.status_code} - {response.text}"
                    
                    data = response.json()
                    # Search results vs List results
                    tickets = data.get("results", []) if "query" in params else data.get("tickets", [])
                    
                    if not tickets:
                        return "No tickets found."

                    results = []
                    for t in tickets:
                        tid = t.get("id")
                        subj = t.get("subject", "No Subject")
                        stat = t.get("status", "unknown")
                        prio = t.get("priority", "none")
                        updated = t.get("updated_at", "")[:16] # Truncate iso
                        results.append(f"- [#{tid}] {subj} (Status: {stat}, Priority: {prio}, Updated: {updated})")
                    
                    return "\n".join(results)

            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "get_tickets",
            "func": get_tickets,
            "schema": {
                "type": "function",
                "function": {
                    "name": "get_tickets",
                    "description": "List recent Zendesk tickets with optional filtering.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max results (default 10)"},
                            "status": {"type": "string", "enum": ["new", "open", "pending", "hold", "solved", "closed"], "description": "Filter by status"},
                            "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "Filter by priority"}
                        }
                    }
                }
            }
        }

    def _tool_get_ticket(self):
        async def get_ticket(ticket_id: int) -> str:
            """Get details of a specific ticket."""
            if not self._authenticated:
                return "Error: Connector not authenticated."

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/tickets/{ticket_id}.json",
                        auth=(f"{self.email}/token", self.api_token)
                    )
                    if response.status_code == 404:
                        return f"Ticket #{ticket_id} not found."
                    if response.status_code != 200:
                        return f"Error: HTTP {response.status_code}"

                    t = response.json().get("ticket", {})
                    
                    details = [
                        f"Ticket #{t.get('id')}: {t.get('subject')}",
                        f"Status: {t.get('status')}",
                        f"Priority: {t.get('priority')}",
                        f"Type: {t.get('type')}",
                        f"Created: {t.get('created_at')}",
                        f"Updated: {t.get('updated_at')}",
                        f"Requester ID: {t.get('requester_id')}",
                        f"Assignee ID: {t.get('assignee_id')}",
                        "---",
                        f"Description:\n{t.get('description')}"
                    ]
                    return "\n".join(details)
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "get_ticket",
            "func": get_ticket,
            "schema": {
                "type": "function",
                "function": {
                    "name": "get_ticket",
                    "description": "Get full details of a specific Zendesk ticket.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {"type": "integer", "description": "Ticket ID"}
                        },
                        "required": ["ticket_id"]
                    }
                }
            }
        }

    def _tool_create_ticket(self):
        async def create_ticket(subject: str, description: str, priority: str = "normal", type: str = "question") -> str:
            """Create a new Zendesk ticket."""
            if not self._authenticated:
                return "Error: Not authenticated."

            body = {
                "ticket": {
                    "subject": subject,
                    "comment": {"body": description},
                    "priority": priority,
                    "type": type
                }
            }
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.base_url}/tickets.json",
                        json=body,
                        auth=(f"{self.email}/token", self.api_token)
                    )
                    if response.status_code != 201:
                        return f"Error creating ticket: {response.text}"
                    
                    t = response.json().get("ticket", {})
                    return f"Ticket created successfully. ID: #{t.get('id')}"
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "create_ticket",
            "func": create_ticket,
            "schema": {
                "type": "function",
                "function": {
                    "name": "create_ticket",
                    "description": "Create a new Zendesk ticket.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string", "description": "Ticket subject"},
                            "description": {"type": "string", "description": "Wait content/description"},
                            "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                            "type": {"type": "string", "enum": ["problem", "incident", "question", "task"]}
                        },
                        "required": ["subject", "description"]
                    }
                }
            }
        }

    def _tool_update_ticket(self):
        async def update_ticket(ticket_id: int, status: str = None, priority: str = None, comment: str = None, public_comment: bool = True) -> str:
            """Update an existing ticket (status, priority, or add comment)."""
            if not self._authenticated:
                return "Error: Not authenticated."

            ticket_data = {}
            if status: ticket_data["status"] = status
            if priority: ticket_data["priority"] = priority
            if comment:
                ticket_data["comment"] = {"body": comment, "public": public_comment}

            if not ticket_data:
                return "No updates specified."

            body = {"ticket": ticket_data}

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.put(
                        f"{self.base_url}/tickets/{ticket_id}.json",
                        json=body,
                        auth=(f"{self.email}/token", self.api_token)
                    )
                    if response.status_code != 200:
                        return f"Error updating ticket: {response.text}"
                    
                    return f"Ticket #{ticket_id} updated successfully."
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "update_ticket",
            "func": update_ticket,
            "schema": {
                "type": "function",
                "function": {
                    "name": "update_ticket",
                    "description": "Update a specific Zendesk ticket.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {"type": "integer"},
                            "status": {"type": "string", "enum": ["open", "pending", "hold", "solved", "closed"]},
                            "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                            "comment": {"type": "string", "description": "Optional comment to add with update"},
                            "public_comment": {"type": "boolean", "description": "If comment is public (default True)"}
                        },
                        "required": ["ticket_id"]
                    }
                }
            }
        }

    def _tool_get_ticket_comments(self):
        async def get_ticket_comments(ticket_id: int) -> str:
            """Get comments for a ticket."""
            if not self._authenticated:
                return "Error: Not authenticated."

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/tickets/{ticket_id}/comments.json",
                        auth=(f"{self.email}/token", self.api_token)
                    )
                    if response.status_code != 200:
                        return f"Error: {response.status_code}"
                    
                    comments = response.json().get("comments", [])
                    if not comments:
                        return "No comments found."
                        
                    results = []
                    for c in comments:
                        author = c.get("author_id", "Unknown") # We could resolve this if we had user cache
                        body = c.get("body", "")
                        created = c.get("created_at", "")
                        public = "Public" if c.get("public") else "Internal"
                        results.append(f"[{created}] User {author} ({public}):\n{body}\n")
                    
                    return "\n".join(results)
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "get_ticket_comments",
            "func": get_ticket_comments,
            "schema": {
                "type": "function",
                "function": {
                    "name": "get_ticket_comments",
                    "description": "Get conversation history for a ticket.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {"type": "integer"}
                        },
                        "required": ["ticket_id"]
                    }
                }
            }
        }

    def _tool_create_ticket_comment(self):
        async def create_ticket_comment(ticket_id: int, comment: str, public: bool = True) -> str:
            """Add a comment to a ticket."""
            # Reuse update logic
            tool = self._tool_update_ticket()["func"]
            return await tool(ticket_id=ticket_id, comment=comment, public_comment=public)

        return {
            "name": "create_ticket_comment",
            "func": create_ticket_comment,
            "schema": {
                "type": "function",
                "function": {
                    "name": "create_ticket_comment",
                    "description": "Add a comment to a Zendesk ticket.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {"type": "integer"},
                            "comment": {"type": "string"},
                            "public": {"type": "boolean", "default": True}
                        },
                        "required": ["ticket_id", "comment"]
                    }
                }
            }
        }
