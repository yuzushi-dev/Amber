# Connectors

<!-- markdownlint-disable MD013 -->

## Overview

External data source connectors enable Amber to integrate with third-party
services for data ingestion and real-time agent interactions.

## Architecture

All connectors extend `BaseConnector` (`src/core/connectors/base.py`) and
implement:

| Method                                | Description                                               |
| ------------------------------------- | --------------------------------------------------------- |
| `authenticate(credentials)`           | Authenticate with the external service                    |
| `fetch_items(since)`                  | Fetch items for RAG ingestion (supports incremental sync) |
| `get_item_content(item_id)`           | Retrieve full content of a specific item                  |
| `list_items(page, page_size, search)` | Paginated listing for UI display                          |
| `test_connection()`                   | Verify the connection is healthy                          |
| `get_agent_tools()`                   | Return tools for the Agent orchestrator                   |

## API Endpoints

All connector endpoints are available at `/v1/connectors`.

| Endpoint                    | Method | Description                        |
| --------------------------- | ------ | ---------------------------------- |
| `/connectors`               | `GET`  | List all available connector types |
| `/connectors/{type}/status` | `GET`  | Get status of a specific connector |
| `/connectors/{type}/auth`   | `POST` | Authenticate with credentials      |
| `/connectors/{type}/sync`   | `POST` | Trigger sync (full or incremental) |
| `/connectors/{type}/items`  | `GET`  | Browse content from the connector  |
| `/connectors/{type}/ingest` | `POST` | Ingest specific items by ID        |

### Request and Response Examples

**Authenticate:**

```http
POST /v1/connectors/carbonio/auth
Content-Type: application/json

{
  "credentials": {
    "host": "https://mail.example.com",
    "email": "user@example.com",
    "password": "secret"
  }
}
```

**Trigger Sync:**

```http
POST /v1/connectors/carbonio/sync
Content-Type: application/json

{
  "full_sync": false
}
```

**List Items:**

```http
GET /v1/connectors/carbonio/items?page=1&page_size=20&search=invoice
```

**Ingest Selected:**

```http
POST /v1/connectors/carbonio/ingest
Content-Type: application/json

{
  "item_ids": ["msg-123", "msg-456"]
}
```

## Available Connectors

### Carbonio (`carbonio`)

**Purpose:** Integrates with Zextras Carbonio suite (Mail, Calendar, Chats).

**Authentication:** SOAP XML authentication with email/password -> returns auth
token.

**Agent Tools:**

| Tool               | Description                                                                                                                                           |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_chats`     | Search chat conversations by person name. Handles disambiguation when multiple people match.                                                          |
| `get_chat_history` | Retrieve message history from a specific chat. Supports date filtering (e.g., "January 9") and keyword search. Uses XMPP/WebSocket for real messages. |
| `search_mail`      | Search emails by query (subject, sender, etc.)                                                                                                        |
| `get_calendar`     | Retrieve calendar events for a date range or specific date.                                                                                           |

**Configuration:**

```json
{
  "host": "https://mail.example.com",
  "email": "user@example.com",
  "password": "<password>"
}
```

**Technical Notes:**

- Uses hybrid protocol: XML SOAP for auth, JSON REST for data
- Chat history retrieval uses XMPP/WebSocket connection with XEP-0313 (MAM)
- Date-aware filtering: queries like "January 9" match message timestamps
- Real-time XMPP handled by `carbonio_xmpp.py`

### Confluence (`confluence`)

**Purpose:** Integrates with Confluence Cloud for wiki/documentation pages.

**Authentication:** Basic Auth with email + API token.

**Features:**

- Fetches pages via Confluence REST API v2
- Supports incremental sync using `updated_at` filtering
- Retrieves page content in storage format (HTML-like)

**Configuration:**

```json
{
  "base_url": "https://domain.atlassian.net/wiki",
  "email": "user@example.com",
  "api_token": "<token>"
}
```

**Agent Tools:**

| Tool           | Description                               |
| -------------- | ----------------------------------------- |
| `search_pages` | Search Confluence pages by CQL query      |
| `get_page`     | Retrieve content of a specific page by ID |
| `add_comment`  | Add a comment to a specific page          |

### Zendesk (`zendesk`)

**Purpose:** Integrates with Zendesk Help Center for support articles and
Support for ticket management.

**Authentication:** API token authentication.

**Features:**

- Fetches articles from Help Center
- Supports incremental sync via `updated_after` filter
- Includes metadata: section, author, votes, draft status
- Full ticket management via Agent tools

**Configuration:**

```json
{
  "subdomain": "mycompany",
  "email": "admin@example.com",
  "api_token": "<token>"
}
```

**Agent Tools:**

| Tool                    | Description                                     |
| ----------------------- | ----------------------------------------------- |
| `get_tickets`           | List/search tickets with filtering              |
| `get_ticket`            | Get details of a specific ticket                |
| `create_ticket`         | Create a new support ticket                     |
| `update_ticket`         | Update ticket status or assignee                |
| `get_ticket_comments`   | Read conversation history of a ticket           |
| `create_ticket_comment` | Add a public reply or internal note to a ticket |

### Jira (`jira`)

**Purpose:** Integrates with Jira Cloud for issue tracking and project
management.

**Authentication:** Basic Auth with email + API token.

**Features:**

- Comprehensive issue management
- JQL search capabilities
- Commenting and collaboration

**Configuration:**

```json
{
  "base_url": "https://domain.atlassian.net",
  "email": "user@example.com",
  "api_token": "<token>"
}
```

**Agent Tools:**

| Tool            | Description                                      |
| --------------- | ------------------------------------------------ |
| `search_issues` | Search issues using JQL (Jira Query Language)    |
| `get_issue`     | Retrieve details of a specific issue by key      |
| `create_issue`  | Create a new issue (Bug, Task, Story, etc.)      |
| `update_issue`  | Update issue fields (summary, description, etc.) |
| `add_comment`   | Add a comment to an issue                        |

## Adding a New Connector

1. Create `src/core/connectors/myservice.py`
2. Extend `BaseConnector` and implement all abstract methods
3. Register in `src/core/connectors/__init__.py`
4. Add to `CONNECTOR_REGISTRY` in `src/api/routes/connectors.py`
5. (Optional) Add Agent tools via `get_agent_tools()` method

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

    async def test_connection(self) -> bool:
        # Test if connection is healthy
        return True

    def get_agent_tools(self):
        # Return tool definitions for Agent
        return []
```

## Connector State Management

Connector state is stored in the `connector_states` table. In the current
implementation, `sync_cursor` is also used to persist connector credentials for
background operations (not encrypted; use a secrets manager in production).

| Field            | Description                          |
| ---------------- | ------------------------------------ |
| `id`             | Connector state ID                   |
| `tenant_id`      | Tenant identifier                    |
| `connector_type` | Unique identifier (e.g., "carbonio") |
| `status`         | `idle`, `syncing`, or `error`        |
| `last_sync_at`   | Timestamp of last successful sync    |
| `sync_cursor`    | Pagination state + credentials (MVP) |
| `error_message`  | Last error, if any                   |

## UI Integration

The frontend Connector Management UI (`/admin/settings/connectors`) provides:

- **Connector Cards**: Visual status for each connector type
- **Authentication Forms**: Service-specific credential input
- **Content Browser**: Browse and select items for ingestion
- **Sync Controls**: Trigger full or incremental sync
- **Status Indicators**: Real-time sync progress and error reporting
