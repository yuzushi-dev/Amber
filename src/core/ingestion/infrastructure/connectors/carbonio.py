import logging
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from src.core.ingestion.infrastructure.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)

# Templates
AUTH_TEMPLATE = """
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Header>
    <context xmlns="urn:zimbra">
      <format type="xml"/>
    </context>
  </soap:Header>
  <soap:Body>
    <AuthRequest xmlns="urn:zimbraAccount">
      <account by="name">{{ email }}</account>
      <password>{{ password }}</password>
    </AuthRequest>
  </soap:Body>
</soap:Envelope>
"""


class CarbonioConnector(BaseConnector):
    """
    Connector for Zextras Carbonio (Mail, Calendar, Chats).
    Uses a hybrid protocol: XML for Auth, JSON for Data.
    """

    def __init__(self, host: str, email: str = "", password: str = ""):
        self.host = host.rstrip("/")  # e.g., https://your-carbonio-host
        self.email = email
        self.password = password
        self.auth_token = None
        self.api_url = f"{self.host}/service/soap"

    def get_connector_type(self) -> str:
        return "carbonio"

    async def authenticate(self, credentials: dict[str, Any]) -> bool:
        """Authenticate using XML SOAP."""
        self.email = credentials.get("email", self.email)
        self.password = credentials.get("password", self.password)
        # Check if host is in credentials (dynamic init)
        if "host" in credentials:
            self.host = credentials["host"].rstrip("/")
            self.api_url = f"{self.host}/service/soap"

        if not self.email or not self.password:
            logger.error("Carbonio auth failed: Missing email or password")
            return False

        auth_xml = (
            AUTH_TEMPLATE.replace("{{ email }}", self.email)
            .replace("{{ password }}", self.password)
            .strip()
        )

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "User-Agent": "AmberCarbonioConnector/1.0",
        }

        try:
            async with httpx.AsyncClient(
                verify=False, follow_redirects=True, timeout=30.0
            ) as client:
                response = await client.post(self.api_url, content=auth_xml, headers=headers)

                if response.status_code != 200:
                    logger.error(
                        f"Carbonio auth HTTP error: {response.status_code} - {response.text}"
                    )
                    return False

                # Parse XML for authToken
                root = ET.fromstring(response.text)
                token = None
                for elem in root.iter():
                    if elem.tag.endswith("authToken"):
                        token = elem.text
                        break

                if token:
                    self.auth_token = token
                    self.cookies = dict(response.cookies)
                    logger.info(f"Carbonio authenticated as {self.email}")
                    logger.info(f"Auth cookies: {list(self.cookies.keys())}")

                    # Fetch User ID (UUID) for XMPP
                    try:
                        info_xml = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
                            <soap:Header>
                                <context xmlns="urn:zimbra">
                                    <authToken>{self.auth_token}</authToken>
                                </context>
                            </soap:Header>
                            <soap:Body>
                                <GetInfoRequest xmlns="urn:zimbraAccount"/>
                            </soap:Body>
                        </soap:Envelope>"""

                        info_resp = await client.post(
                            self.api_url, content=info_xml, headers=headers
                        )
                        if info_resp.status_code == 200:
                            info_root = ET.fromstring(info_resp.text)
                            for elem in info_root.iter():
                                if (
                                    elem.tag.endswith("id") and len(elem.text or "") > 20
                                ):  # Heuristic for UUID
                                    self.user_id = elem.text
                                    logger.info(f"Captured User ID: {self.user_id}")
                                    break
                                # Also check attributes if it's <account id="...">
                                # GetInfoResponse usually has <id>...</id> inside <account> or similar?
                                # Actually GetInfoResponse -> id is usually an element text content or attribute of account

                            # Better parsing for GetInfoResponse
                            # <GetInfoResponse><id>UUID</id>...</GetInfoResponse>
                            if not hasattr(self, "user_id"):
                                # Try finding 'id' tag specifically
                                for elem in info_root.iter():
                                    if elem.tag.endswith("id") and elem.text:
                                        self.user_id = elem.text
                                        logger.info(f"Captured User ID (tag): {self.user_id}")
                                        break
                    except Exception as e:
                        logger.warning(f"Failed to fetch User ID: {e}")

                    return True
                else:
                    logger.error("Carbonio auth failed: No authToken in response")
                    return False

        except Exception as e:
            logger.exception(f"Carbonio auth exception: {e}")
            return False

    def _build_json_request(self, request_type: str, body_content: dict) -> dict:
        return {
            "Header": {
                "context": {"_jsns": "urn:zimbra", "authToken": {"_content": self.auth_token}}
            },
            "Body": {request_type: body_content},
        }

    async def fetch_items(self, since: datetime | None = None) -> AsyncIterator[ConnectorItem]:
        """Fetch emails (TODO: and Calendar/Chats) for RAG ingestion."""
        # For MVP, just sync recent emails from Inbox
        if not self.auth_token:
            if not await self.authenticate({"email": self.email, "password": self.password}):
                return

        # Use JSON for data
        body = {
            "_jsns": "urn:zimbraMail",
            "types": "message",  # Fetch emails
            "limit": 50,
            "query": "in:inbox",
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                req = self._build_json_request("SearchRequest", body)
                resp = await client.post(self.api_url, json=req)

                if resp.status_code != 200:
                    logger.error(f"Fetch items failed: {resp.status_code}")
                    return

                data = resp.json()
                items = data.get("Body", {}).get("SearchResponse", {}).get("m", [])

                for item in items:
                    # Parse subject
                    subject = item.get("su", "No Subject")
                    if isinstance(subject, list):
                        subject = subject[0].get("_content", "No Subject")

                    item_id = item.get("id")

                    yield ConnectorItem(
                        id=item_id,
                        title=subject,
                        url=f"{self.host}/?id={item_id}",  # Deep link?
                        updated_at=datetime.fromtimestamp(item.get("d", 0) / 1000),
                        content_type="text/html",
                        metadata={
                            "sender": item.get("e", [{}])[0].get("a", "unknown"),
                            "snippet": item.get("fr", ""),
                        },
                    )

        except Exception as e:
            logger.error(f"Fetch items error: {e}")

    async def get_item_content(self, item_id: str) -> bytes:
        """Get full content of an email."""
        # TODO: Implement GetMsgRequest
        return b"Pass"

    async def list_items(
        self, page: int = 1, page_size: int = 20, search: str = None
    ) -> tuple[list[ConnectorItem], bool]:
        """List items for the UI with proper pagination."""
        all_items = []
        # Fetch enough items to know if there are more
        items_to_fetch = (page * page_size) + 1  # +1 to check for has_more

        async for item in self.fetch_items():
            all_items.append(item)
            if len(all_items) >= items_to_fetch:
                break

        # Calculate pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        page_items = all_items[start_idx:end_idx]
        has_more = len(all_items) > end_idx

        return page_items, has_more

    # --- Agent Tools ---

    def get_agent_tools(self) -> list[dict[str, Any]]:
        return [
            self._tool_search_mail(),
            self._tool_get_calendar(),
        ]

    def _tool_search_mail(self):
        async def search_mail(query: str, limit: int = 5) -> str:
            """Search emails in Carbonio."""
            if not self.auth_token:
                # Try to re-auth? Currently needs credentials in instance
                return "Error: Connector not authenticated."

            body = {"_jsns": "urn:zimbraMail", "types": "message", "limit": limit, "query": query}

            try:
                async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                    req = self._build_json_request("SearchRequest", body)
                    resp = await client.post(self.api_url, json=req)

                    if resp.status_code != 200:
                        return f"Error: HTTP {resp.status_code}"

                    data = resp.json()
                    msgs = data.get("Body", {}).get("SearchResponse", {}).get("m", [])

                    if not msgs:
                        return "No emails found."

                    results = []
                    for m in msgs:
                        su = m.get("su", "No Subject")
                        if isinstance(su, list):
                            su = su[0].get("_content", "No Subject")
                        sender = m.get("e", [{}])[0].get("a", "unknown")
                        date = datetime.fromtimestamp(m.get("d", 0) / 1000).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                        results.append(f"- [{date}] From: {sender} | Subj: {su}")

                    return "\n".join(results)

            except Exception as e:
                return f"Exception: {e}"

        return {
            "name": "search_mail",
            "func": search_mail,
            "schema": {
                "type": "function",
                "function": {
                    "name": "search_mail",
                    "description": "Search for emails in the user's mailbox.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (e.g. 'from:boss', 'subject:urgent')",
                            },
                            "limit": {"type": "integer", "description": "Max results"},
                        },
                        "required": ["query"],
                    },
                },
            },
        }

    def _tool_get_calendar(self):
        async def get_calendar_events(days: int = 7, date: str = None) -> str:
            """Get calendar events for a date range or specific date."""
            if not self.auth_token:
                return "Error: Connector not authenticated."

            from datetime import timedelta

            # Determine date range
            if date:
                # Try to parse a specific date like "January 21" or "21 January"
                try:
                    import re

                    # Extract day and month
                    match = re.search(
                        r"(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\w+)?",
                        date.lower(),
                    )
                    if match:
                        day = int(match.group(1))
                        month_str = match.group(2) if match.group(2) else None

                        months = {
                            "jan": 1,
                            "feb": 2,
                            "mar": 3,
                            "apr": 4,
                            "may": 5,
                            "jun": 6,
                            "jul": 7,
                            "aug": 8,
                            "sep": 9,
                            "oct": 10,
                            "nov": 11,
                            "dec": 12,
                            "january": 1,
                            "february": 2,
                            "march": 3,
                            "april": 4,
                            "june": 6,
                            "july": 7,
                            "august": 8,
                            "september": 9,
                            "october": 10,
                            "november": 11,
                            "december": 12,
                        }

                        month = (
                            months.get(month_str, datetime.now().month)
                            if month_str
                            else datetime.now().month
                        )
                        year = datetime.now().year
                        # If month is past, assume next year
                        if month < datetime.now().month:
                            year += 1
                        start_dt = datetime(year, month, day, 0, 0, 0)
                        end_dt = start_dt + timedelta(days=1)
                    else:
                        start_dt = datetime.now()
                        end_dt = start_dt + timedelta(days=days)
                except Exception:
                    start_dt = datetime.now()
                    end_dt = start_dt + timedelta(days=days)
            else:
                start_dt = datetime.now()
                end_dt = start_dt + timedelta(days=days)

            # Convert to milliseconds
            start_ms = int(start_dt.timestamp() * 1000)
            end_ms = int(end_dt.timestamp() * 1000)

            logger.info(f"Calendar query: {start_dt} to {end_dt}")

            # Use GetApptSummariesRequest for calendar
            body = {"_jsns": "urn:zimbraMail", "s": start_ms, "e": end_ms}

            try:
                async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                    req = self._build_json_request("GetApptSummariesRequest", body)
                    resp = await client.post(self.api_url, json=req)

                    logger.info(f"Calendar API response: {resp.status_code}")

                    data = resp.json()
                    appts = data.get("Body", {}).get("GetApptSummariesResponse", {}).get("appt", [])

                    logger.info(f"Found {len(appts)} appointments")

                    if not appts:
                        return (
                            f"No upcoming appointments found for {start_dt.strftime('%B %d, %Y')}."
                        )

                    results = []
                    for a in appts:
                        name = a.get("name", "No Title")
                        # Parse start time from instances 'inst' if available
                        start_ts = 0
                        if "inst" in a and a["inst"]:
                            start_ts = a["inst"][0].get("s", 0)
                        elif "d" in a:
                            start_ts = a["d"]

                        date_str = datetime.fromtimestamp(start_ts / 1000).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                        results.append(f"- [{date_str}] {name}")

                    return "\n".join(results)

            except Exception as e:
                logger.error(f"Calendar exception: {e}")
                return f"Exception: {e}"

        return {
            "name": "get_calendar_events",
            "func": get_calendar_events,
            "schema": {
                "type": "function",
                "function": {
                    "name": "get_calendar_events",
                    "description": "Get calendar events for a date range or specific date.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "Number of days to look ahead (default 7)",
                            },
                            "date": {
                                "type": "string",
                                "description": "Specific date to check (e.g. 'January 21', '21 Jan')",
                            },
                        },
                    },
                },
            },
        }
