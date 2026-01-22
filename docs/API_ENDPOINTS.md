# Amber API Endpoints Reference

> **Amber — Preserving Context, Revealing Insight**

This document provides a comprehensive reference of all API endpoints available in the Amber system. The API combines vector similarity search with knowledge graph reasoning to deliver contextual, sourced, and high-quality answers over document collections.

---

## Authentication

All endpoints (except health checks) require an API key. Pass your key in the `X-API-Key` header.

---

## Table of Contents

- [Health & Setup](#health--setup)
- [Query](#query)
- [Documents](#documents)
- [Events](#events)
- [Connectors](#connectors)
- [Feedback](#feedback)
- [Export](#export)
- [Folders](#folders)
- [Graph Editor](#graph-editor)
- [Graph History](#graph-history)
- [Admin - Jobs](#admin---jobs)
- [Admin - Configuration](#admin---configuration)
- [Admin - Curation](#admin---curation)
- [Admin - Maintenance](#admin---maintenance)
- [Admin - Chat History](#admin---chat-history)
- [Admin - Ragas Benchmarks](#admin---ragas-benchmarks)

---

## Health & Setup

### Health Checks

| Method | Endpoint            | Description                                      |
| ------ | ------------------- | ------------------------------------------------ |
| `GET`  | `/health`           | Liveness probe - returns 200 if process is alive |
| `GET`  | `/health/ready`     | Readiness probe - checks all dependencies        |
| `GET`  | `/api/health`       | Liveness probe (alternate path)                  |
| `GET`  | `/api/health/ready` | Readiness probe (alternate path)                 |

### Setup

| Method | Endpoint                    | Description                                                 |
| ------ | --------------------------- | ----------------------------------------------------------- |
| `GET`  | `/api/setup/status`         | Get current setup status and installed features             |
| `POST` | `/api/setup/install`        | Install optional features in the background                 |
| `POST` | `/api/setup/skip`           | Mark setup complete without installing features             |
| `GET`  | `/api/setup/check-required` | Verify required services (PostgreSQL, Neo4j, Milvus, Redis) |

---

## Query

| Method | Endpoint           | Description                                           |
| ------ | ------------------ | ----------------------------------------------------- |
| `POST` | `/v1/query`        | Submit natural language query to retrieve information |
| `GET`  | `/v1/query/stream` | Stream query response via Server-Sent Events          |
| `POST` | `/v1/query/stream` | Stream query response via Server-Sent Events (POST)   |

### Query Request Body

```json
{
  "query": "What are the main features?",
  "filters": {
    "document_ids": ["doc_123"],
    "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
    "tags": ["important"]
  },
  "options": {
    "search_mode": "basic|local|global|drift|structured",
    "use_hyde": false,
    "use_rewrite": true,
    "use_decomposition": false,
    "include_trace": false,
    "max_chunks": 10,
    "traversal_depth": 2,
    "include_sources": true,
    "stream": false
  },
  "conversation_id": "optional-conversation-id"
}
```

---

## Documents

| Method   | Endpoint                                    | Description                                          |
| -------- | ------------------------------------------- | ---------------------------------------------------- |
| `POST`   | `/v1/documents`                             | Upload document for ingestion (returns 202 Accepted) |
| `GET`    | `/v1/documents`                             | List all documents (supports pagination)             |
| `GET`    | `/v1/documents/{document_id}`               | Get document details including enrichment data       |
| `DELETE` | `/v1/documents/{document_id}`               | Delete a document                                    |
| `GET`    | `/v1/documents/{document_id}/file`          | Download original document file                      |
| `GET`    | `/v1/documents/{document_id}/chunks`        | Get document chunks with pagination                  |
| `GET`    | `/v1/documents/{document_id}/entities`      | Get extracted entities with pagination               |
| `GET`    | `/v1/documents/{document_id}/relationships` | Get entity relationships with pagination             |
| `GET`    | `/v1/documents/{document_id}/communities`   | Get entity clusters/communities                      |

### Document Upload

```bash
curl -X POST /v1/documents \
  -H "X-API-Key: your-key" \
  -F "file=@document.pdf" \
  -F "tenant_id=default"
```

---

## Events

| Method | Endpoint                             | Description                               |
| ------ | ------------------------------------ | ----------------------------------------- |
| `GET`  | `/v1/documents/{document_id}/events` | Stream document processing events via SSE |

---

## Connectors

| Method   | Endpoint                                   | Description                        |
| -------- | ------------------------------------------ | ---------------------------------- |
| `GET`    | `/v1/connectors`                           | List available connectors          |
| `GET`    | `/v1/connectors/{connector_id}`            | Get connector details              |
| `POST`   | `/v1/connectors/{connector_id}/connect`    | Connect to a data source           |
| `POST`   | `/v1/connectors/{connector_id}/sync`       | Trigger sync from connected source |
| `DELETE` | `/v1/connectors/{connector_id}/disconnect` | Disconnect from data source        |

> See [CONNECTORS.md](./CONNECTORS.md) for detailed connector documentation.

---

## Feedback

| Method | Endpoint                    | Description                          |
| ------ | --------------------------- | ------------------------------------ |
| `POST` | `/v1/feedback`              | Submit feedback for a query response |
| `GET`  | `/v1/feedback/{request_id}` | Get feedback for a specific request  |

> See [FEEDBACK_SYSTEM.md](./FEEDBACK_SYSTEM.md) for detailed feedback documentation.

---

## Export

| Method | Endpoint                  | Description                            |
| ------ | ------------------------- | -------------------------------------- |
| `POST` | `/v1/export/conversation` | Export conversation to various formats |
| `GET`  | `/v1/export/formats`      | List available export formats          |

---

## Folders

| Method   | Endpoint                  | Description         |
| -------- | ------------------------- | ------------------- |
| `GET`    | `/v1/folders`             | List all folders    |
| `POST`   | `/v1/folders`             | Create a new folder |
| `GET`    | `/v1/folders/{folder_id}` | Get folder details  |
| `PUT`    | `/v1/folders/{folder_id}` | Update folder       |
| `DELETE` | `/v1/folders/{folder_id}` | Delete folder       |

---

## Graph Editor

| Method   | Endpoint                                    | Description                  |
| -------- | ------------------------------------------- | ---------------------------- |
| `GET`    | `/v1/graph/entities`                        | List entities with filtering |
| `GET`    | `/v1/graph/entities/{entity_id}`            | Get entity details           |
| `PUT`    | `/v1/graph/entities/{entity_id}`            | Update entity                |
| `DELETE` | `/v1/graph/entities/{entity_id}`            | Delete entity                |
| `POST`   | `/v1/graph/entities/merge`                  | Merge duplicate entities     |
| `GET`    | `/v1/graph/relationships`                   | List relationships           |
| `DELETE` | `/v1/graph/relationships/{relationship_id}` | Delete relationship          |

---

## Graph History

| Method | Endpoint                             | Description             |
| ------ | ------------------------------------ | ----------------------- |
| `GET`  | `/v1/graph/history`                  | List graph edit history |
| `GET`  | `/v1/graph/history/{edit_id}`        | Get edit details        |
| `POST` | `/v1/graph/history/{edit_id}/revert` | Revert a graph edit     |

---

## Admin - Jobs

| Method | Endpoint                          | Description                         |
| ------ | --------------------------------- | ----------------------------------- |
| `GET`  | `/v1/admin/jobs`                  | List active and recent Celery tasks |
| `GET`  | `/v1/admin/jobs/{task_id}`        | Get task details and status         |
| `POST` | `/v1/admin/jobs/{task_id}/cancel` | Cancel or revoke a task             |
| `GET`  | `/v1/admin/jobs/queues/status`    | Get queue depths and worker status  |

### Job Status Values

- `PENDING` - Task is waiting in queue
- `STARTED` - Task has begun execution
- `PROGRESS` - Task is running with progress updates
- `SUCCESS` - Task completed successfully
- `FAILURE` - Task failed with error
- `REVOKED` - Task was cancelled
- `RETRY` - Task is being retried

---

## Admin - Configuration

| Method | Endpoint                                     | Description                     |
| ------ | -------------------------------------------- | ------------------------------- |
| `GET`  | `/v1/admin/config/schema`                    | Get configuration schema for UI |
| `GET`  | `/v1/admin/config/tenants/{tenant_id}`       | Get tenant configuration        |
| `PUT`  | `/v1/admin/config/tenants/{tenant_id}`       | Update tenant configuration     |
| `POST` | `/v1/admin/config/tenants/{tenant_id}/reset` | Reset tenant config to defaults |

### Configurable Parameters

| Parameter                 | Type    | Default                  | Description                |
| ------------------------- | ------- | ------------------------ | -------------------------- |
| `top_k`                   | integer | 10                       | Max chunks to retrieve     |
| `expansion_depth`         | integer | 2                        | Graph traversal depth      |
| `similarity_threshold`    | float   | 0.7                      | Minimum similarity score   |
| `reranking_enabled`       | boolean | true                     | Enable FlashRank reranking |
| `hyde_enabled`            | boolean | false                    | Enable HyDE embeddings     |
| `graph_expansion_enabled` | boolean | true                     | Enable graph expansion     |
| `embedding_model`         | string  | `text-embedding-3-small` | Embedding model            |
| `generation_model`        | string  | `gpt-4o-mini`            | LLM model                  |
| `system_prompt_override`  | string  | null                     | Custom system prompt       |

---

## Admin - Curation

| Method | Endpoint                             | Description                        |
| ------ | ------------------------------------ | ---------------------------------- |
| `GET`  | `/v1/admin/curation/flags`           | List curation flags with filters   |
| `POST` | `/v1/admin/curation/flags`           | Create a new flag                  |
| `GET`  | `/v1/admin/curation/flags/{flag_id}` | Get flag details with context      |
| `PUT`  | `/v1/admin/curation/flags/{flag_id}` | Resolve flag (accept/reject/merge) |
| `GET`  | `/v1/admin/curation/stats`           | Get curation queue statistics      |

### Flag Resolution Actions

- `accept` - Accept the flag and apply correction
- `reject` - Reject the flag (false positive)
- `merge` - Merge entities (requires `merge_target_id`)

---

## Admin - Maintenance

| Method | Endpoint                                        | Description                          |
| ------ | ----------------------------------------------- | ------------------------------------ |
| `GET`  | `/v1/admin/maintenance/stats`                   | Get comprehensive system statistics  |
| `POST` | `/v1/admin/maintenance/cache/clear`             | Clear Redis cache (optional pattern) |
| `POST` | `/v1/admin/maintenance/prune/orphans`           | Remove orphan graph nodes            |
| `POST` | `/v1/admin/maintenance/prune/stale-communities` | Remove old community summaries       |
| `GET`  | `/v1/admin/maintenance/reconciliation`          | Get dual-write sync status           |
| `POST` | `/v1/admin/maintenance/reindex`                 | Trigger vector index rebuild         |
| `GET`  | `/v1/admin/maintenance/vectors/collections`     | Get Milvus collection details        |

---

## Admin - Chat History

| Method | Endpoint                              | Description                    |
| ------ | ------------------------------------- | ------------------------------ |
| `GET`  | `/v1/admin/chat/history`              | List recent chat conversations |
| `GET`  | `/v1/admin/chat/history/{request_id}` | Get full conversation details  |

---

## Admin - Ragas Benchmarks

| Method | Endpoint                        | Description                        |
| ------ | ------------------------------- | ---------------------------------- |
| `GET`  | `/v1/admin/ragas/stats`         | Get overall benchmark statistics   |
| `GET`  | `/v1/admin/ragas/datasets`      | List available golden datasets     |
| `POST` | `/v1/admin/ragas/datasets`      | Upload new golden dataset (JSON)   |
| `POST` | `/v1/admin/ragas/run-benchmark` | Trigger benchmark run              |
| `GET`  | `/v1/admin/ragas/job/{job_id}`  | Get benchmark run status/results   |
| `GET`  | `/v1/admin/ragas/comparison`    | Compare multiple benchmark runs    |
| `GET`  | `/v1/admin/ragas/runs`          | List benchmark runs with filtering |

---

## Response Codes

| Code  | Description                                |
| ----- | ------------------------------------------ |
| `200` | Success                                    |
| `202` | Accepted (async operation started)         |
| `204` | No Content (successful deletion)           |
| `400` | Bad Request                                |
| `401` | Unauthorized (missing/invalid API key)     |
| `404` | Not Found                                  |
| `422` | Validation Error                           |
| `500` | Internal Server Error                      |
| `503` | Service Unavailable (dependency unhealthy) |

---

## OpenAPI Specification

The complete OpenAPI 3.1 specification is available at:
- **Interactive Docs**: `/docs` (Swagger UI)
- **ReDoc**: `/redoc`
- **JSON Spec**: `/openapi.json`

---

*Last updated: January 2026*
