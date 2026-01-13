"""
Jira Connector
==============

Connector for Jira Cloud.
"""

import logging
from typing import Any
import httpx

from src.core.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class JiraConnector(BaseConnector):
    """
    Connector for Jira Cloud.
    
    Authenticates via Email + API Token (Basic Auth).
    """

    def __init__(self, base_url: str = None, email: str = None, api_token: str = None):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.email = email
        self.api_token = api_token
        self._authenticated = False

    async def authenticate(self, credentials: dict[str, Any]) -> bool:
        """Authenticate with Jira Cloud."""
        base_url = credentials.get("base_url", self.base_url)
        email = credentials.get("email", self.email)
        api_token = credentials.get("api_token", self.api_token)

        if not base_url or not email or not api_token:
            logger.error("Jira credentials incomplete (need base_url, email, api_token)")
            return False

        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token

        # Test auth (Get Current User)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/rest/api/3/myself",
                    auth=(email, api_token)
                )
                response.raise_for_status()
                self._authenticated = True
                logger.info(f"Authenticated with Jira as {email}")
                return True
        except Exception as e:
            logger.error(f"Jira authentication failed: {e}")
            return False

    def get_agent_tools(self) -> list[dict[str, Any]]:
        return [
            self._tool_get_issues(),
            self._tool_get_issue(),
            self._tool_create_issue(),
            self._tool_update_issue(),
            self._tool_add_comment(),
        ]

    def _tool_get_issues(self):
        async def get_issues(jql: str = "order by created DESC", limit: int = 10) -> str:
            """Search Jira issues using JQL."""
            if not self._authenticated: return "Error: Not authenticated."
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/rest/api/3/search",
                        params={"jql": jql, "maxResults": limit, "fields": "summary,status,assignee,priority,created"},
                        auth=(self.email, self.api_token)
                    )
                    if response.status_code != 200:
                        return f"Error: {response.status_code} - {response.text}"
                    
                    issues = response.json().get("issues", [])
                    if not issues: return "No issues found."
                    
                    results = []
                    for i in issues:
                        key = i.get("key")
                        fields = i.get("fields", {})
                        summary = fields.get("summary", "No Summary")
                        status = fields.get("status", {}).get("name", "Unknown")
                        prio = fields.get("priority", {}).get("name", "None")
                        assignee = fields.get("assignee", {}) or {}
                        assignee_name = assignee.get("displayName", "Unassigned")
                        
                        results.append(f"- [{key}] {summary} (Status: {status}, Priority: {prio}, Assignee: {assignee_name})")
                    
                    return "\n".join(results)
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "get_issues",
            "func": get_issues,
            "schema": {
                "type": "function",
                "function": {
                    "name": "get_issues",
                    "description": "Search Jira issues using JQL.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "jql": {"type": "string", "description": "JQL Query (e.g., 'project=PROJ AND status=Open')"},
                            "limit": {"type": "integer", "default": 10}
                        },
                        "required": ["jql"]
                    }
                }
            }
        }

    def _tool_get_issue(self):
        async def get_issue(issue_key: str) -> str:
            """Get details of a specific issue."""
            if not self._authenticated: return "Error: Not authenticated."
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/rest/api/3/issue/{issue_key}",
                        auth=(self.email, self.api_token)
                    )
                    if response.status_code == 404: return f"Issue {issue_key} not found."
                    if response.status_code != 200: return f"Error: {response.status_code}"
                    
                    data = response.json()
                    fields = data.get("fields", {})
                    
                    # Get comments (usually expanded or separate request, but often included in issue detail by default)
                    comments_data = fields.get("comment", {}).get("comments", [])
                    comments_text = []
                    for c in comments_data[-5:]: # Last 5
                         author = c.get("author", {}).get("displayName", "Unknown")
                         body = c.get("body", {}) # Jira V3 uses ADF (complex struct) or Rendered?
                         # Simplifying: Jira V3 usually returns 'content' in ADF. 
                         # FOR MVP: We rely on 'renderedFields' if available or raw text structure if simple.
                         # Actually, getting rendered description is easier.
                         pass 
                    
                    # Re-fetch with renderedFields for easier text parsing
                    # (Note: Requires complex logic to parse ADF, let's try to get 'renderedFields' via expand)
                    pass

                # RETRY with expand=renderedFields
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/rest/api/3/issue/{issue_key}",
                        params={"expand": "renderedFields"},
                        auth=(self.email, self.api_token)
                    )
                    data = response.json()
                    r_fields = data.get("renderedFields", {})
                    fields = data.get("fields", {})
                    
                    desc = r_fields.get("description", "No description") # HTML format
                    
                    # Clean HTML for Agent? Agent can handle HTML chunks usually.
                    
                    details = [
                        f"Issue: {data.get('key')}",
                        f"Summary: {fields.get('summary')}",
                        f"Status: {fields.get('status', {}).get('name')}",
                        f"Assignee: {fields.get('assignee', {}).get('displayName') if fields.get('assignee') else 'Unassigned'}",
                        "---",
                        f"Description: {desc[:2000]}..." # Truncate heavily
                    ]
                    return "\n".join(details)
                    
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "get_issue",
            "func": get_issue,
            "schema": {
                "type": "function",
                "function": {
                    "name": "get_issue",
                    "description": "Get details of a Jira issue.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "issue_key": {"type": "string", "description": "Issue Key (e.g. PROJ-123)"}
                        },
                        "required": ["issue_key"]
                    }
                }
            }
        }

    def _tool_create_issue(self):
        async def create_issue(project_key: str, summary: str, description: str, issuetype: str = "Task") -> str:
            """Create a new Jira issue."""
            if not self._authenticated: return "Error: Not authenticated."
            
            # Jira V3 Create Payload (Using ADF for description is complex -> Use V2 string or simple ADF)
            # Most versatile: Use simple ADF structure for V3
            adf_description = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}]
                    }
                ]
            }

            body = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": summary,
                    "description": adf_description,
                    "issuetype": {"name": issuetype}
                }
            }
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.base_url}/rest/api/3/issue",
                        json=body,
                        auth=(self.email, self.api_token)
                    )
                    if response.status_code != 201:
                        return f"Error creating issue: {response.text}"
                    
                    return f"Issue created: {response.json().get('key')}"
            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "create_issue",
            "func": create_issue,
            "schema": {
                "type": "function",
                "function": {
                    "name": "create_issue",
                    "description": "Create a new Jira issue.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "project_key": {"type": "string"},
                            "summary": {"type": "string"},
                            "description": {"type": "string"},
                            "issuetype": {"type": "string", "enum": ["Task", "Bug", "Story", "Epic"]}
                        },
                        "required": ["project_key", "summary", "description"]
                    }
                }
            }
        }

    def _tool_update_issue(self):
        async def update_issue(issue_key: str, comment: str = None) -> str:
            """Update issue (comment only for now)."""
            if not self._authenticated: return "Error: Not authenticated."
            
            # Transition logic is complex (needs transition ID).
            # For MVP Agent, commenting is 90% of the work.
            if comment:
                return await self._add_comment_internal(issue_key, comment)
            return "No updates requested."

        return {
            "name": "update_issue",
            "func": update_issue,
            "schema": {
                "type": "function",
                "function": {
                    "name": "update_issue",
                    "description": "Update/Comment on a Jira issue.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "issue_key": {"type": "string"},
                            "comment": {"type": "string"}
                        },
                        "required": ["issue_key"]
                    }
                }
            }
        }

    def _tool_add_comment(self):
         async def add_comment(issue_key: str, comment: str) -> str:
             return await self._add_comment_internal(issue_key, comment)

         return {
            "name": "add_comment",
            "func": add_comment,
            "schema": {
                "type": "function",
                "function": {
                    "name": "add_comment",
                    "description": "Add a comment to a Jira issue.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "issue_key": {"type": "string"},
                            "comment": {"type": "string"}
                        },
                        "required": ["issue_key", "comment"]
                    }
                }
            }
         }

    async def _add_comment_internal(self, issue_key: str, comment: str) -> str:
        # ADF Comment
        body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}]
                    }
                ]
            }
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/rest/api/3/issue/{issue_key}/comment",
                    json=body,
                    auth=(self.email, self.api_token)
                )
                if response.status_code != 201:
                     return f"Error adding comment: {response.text}"
                return f"Comment added to {issue_key}"
        except Exception as e:
            return f"Exception: {e}"
