# Connectors

External data source connectors enable Amber to integrate with third-party services for data ingestion and real-time agent interactions.

## Architecture

All connectors extend `BaseConnector` (`src/core/connectors/base.py`) and implement:

| Method                                | Description                                               |
| ------------------------------------- | --------------------------------------------------------- |
| `authenticate(credentials)`           | Authenticate with the external service                    |
| `fetch_items(since)`                  | Fetch items for RAG ingestion (supports incremental sync) |
| `get_item_content(item_id)`           | Retrieve full content of a specific item                  |
| `list_items(page, page_size, search)` | Paginated listing for UI display                          |
| `get_agent_tools()`                   | Return tools for the Agent orchestrator                   |

---

## Available Connectors

### 1. Carbonio (`carbonio`)

**Purpose:** Integrates with Zextras Carbonio suite (Mail, Calendar, Chats).

**Authentication:** SOAP XML authentication with email/password → returns auth token.

**Agent Tools:**
| Tool               | Description                                                                                                                                           |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_chats`     | Search chat conversations by person name. Handles disambiguation when multiple people match.                                                          |
| `get_chat_history` | Retrieve message history from a specific chat. Supports date filtering (e.g., "January 9") and keyword search. Uses XMPP/WebSocket for real messages. |
| `search_mail`      | Search emails by query.                                                                                                                               |
| `get_calendar`     | Retrieve calendar events for a date range.                                                                                                            |

**Configuration:**
```env
# Set via ConnectorState in database
host: https://mail.example.com
email: user@example.com
password: <password>
```

**Technical Notes:**
- Uses hybrid protocol: XML SOAP for auth, JSON REST for data
- Chat history retrieval uses XMPP/WebSocket connection with XEP-0313 (MAM)
- Date-aware filtering: queries like "January 9" match message timestamps

---

### 2. Confluence (`confluence`)

**Purpose:** Integrates with Confluence Cloud for wiki/documentation pages.

**Authentication:** Basic Auth with email + API token.

**Features:**
- Fetches pages via Confluence REST API v2
- Supports incremental sync using `updated_at` filtering
- Retrieves page content in storage format (HTML-like)

**Configuration:**
```env
CONFLUENCE_BASE_URL=https://domain.atlassian.net/wiki
CONFLUENCE_EMAIL=user@example.com
CONFLUENCE_API_TOKEN=<token>
```

**Agent Tools:** None (data ingestion only)

---

### 3. Zendesk (`zendesk`)

**Purpose:** Integrates with Zendesk Help Center for support articles.

**Authentication:** API token authentication.

**Features:**
- Fetches articles from Help Center
- Supports incremental sync via `updated_after` filter
- Includes metadata: section, author, votes, draft status

**Configuration:**
```env
ZENDESK_SUBDOMAIN=mycompany
ZENDESK_EMAIL=admin@example.com
ZENDESK_API_TOKEN=<token>
```

**Agent Tools:** None (data ingestion only)

---

## Adding a New Connector

1. Create `src/core/connectors/myservice.py`
2. Extend `BaseConnector` and implement all abstract methods
3. Register in `src/core/connectors/__init__.py`
4. (Optional) Add Agent tools via `get_agent_tools()` method

```python
from src.core.connectors.base import BaseConnector, ConnectorItem

class MyServiceConnector(BaseConnector):
    def get_connector_type(self) -> str:
        return "myservice"
    
    async def authenticate(self, credentials: dict) -> bool:
        # Implement authentication
        pass
    
    async def fetch_items(self, since=None):
        # Yield ConnectorItem instances
        pass
    
    async def get_item_content(self, item_id: str) -> bytes:
        # Return raw content
        pass
    
    async def list_items(self, page=1, page_size=20, search=None):
        # Return (items, has_more)
        pass
    
    def get_agent_tools(self):
        # Return tool definitions for Agent
        return []
```

---

## Connector State Management

Connector credentials are stored encrypted in the `connector_states` table:

| Field            | Description                          |
| ---------------- | ------------------------------------ |
| `connector_type` | Unique identifier (e.g., "carbonio") |
| `credentials`    | Encrypted JSON blob                  |
| `last_sync`      | Timestamp of last successful sync    |
| `enabled`        | Active/inactive toggle               |

API Endpoints:
- `GET /v1/connectors` - List configured connectors
- `POST /v1/connectors/{type}/connect` - Initialize/reconnect
- `DELETE /v1/connectors/{type}` - Remove connector
