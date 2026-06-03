# Amber API Endpoints Reference

<!-- markdownlint-disable MD013 -->

## Overview

This document provides a comprehensive reference of all API endpoints available in the Amber system. The API combines vector similarity search with knowledge graph reasoning to deliver contextual, sourced, and high-quality answers over document collections.

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Health & Setup](#health--setup)
  - [Health Checks](#health-checks)
  - [Setup (Admin)](#setup-admin)
- [Query](#query)
  - [Query Request Body](#query-request-body)
- [Documents](#documents)
  - [Document Upload](#document-upload)
- [Communities](#communities)
- [Connectors](#connectors)
- [Feedback](#feedback)
- [Export](#export)
- [Folders](#folders)
- [Graph Editor](#graph-editor)
- [Graph History](#graph-history)
- [Admin - Jobs](#admin---jobs)
  - [Job Status Values](#job-status-values)
- [Admin - Configuration](#admin---configuration)
  - [Configurable Parameters](#configurable-parameters)
- [Admin - Curation](#admin---curation)
  - [Flag Resolution Actions](#flag-resolution-actions)
- [Admin - Maintenance](#admin---maintenance)
- [Admin - Chat History](#admin---chat-history)
- [Admin - Ragas Benchmarks](#admin---ragas-benchmarks)
- [Admin - Keys](#admin---keys)
- [Admin - Tenants](#admin---tenants)
- [Admin - Feedback](#admin---feedback)
- [Admin - Rules](#admin---rules)
- [Admin - Context Graph](#admin---context-graph)
- [Admin - Retention](#admin---retention)
- [Admin - Embeddings](#admin---embeddings)
- [Admin - Providers](#admin---providers)
- [Admin - Seed Data](#admin---seed-data)
- [Admin - Backup](#admin---backup)
- [Admin - Observability](#admin---observability)
- [Admin - Provisioning](#admin---provisioning)
- [Authentication Ticket](#authentication-ticket)
- [Chat History (User)](#chat-history-user)
- [Groups](#groups)
- [Response Codes](#response-codes)
- [OpenAPI Specification](#openapi-specification)

## Authentication

All endpoints (except health checks) require an API key. Pass your key in the `X-API-Key` header.

## Health & Setup

### Health Checks

| Method | Endpoint           | Description                                      |
| ------ | ------------------ | ------------------------------------------------ |
| `GET`  | `/health`          | Liveness probe - returns 200 if process is alive |
| `GET`  | `/health/ready`    | Readiness probe - checks all dependencies        |
| `GET`  | `/v1/health`       | Liveness probe (versioned)                       |
| `GET`  | `/v1/health/ready` | Readiness probe (versioned)                      |

### Setup (Admin)

All setup endpoints require an API key with `super_admin` scope.

| Method | Endpoint                   | Description                             |
| ------ | -------------------------- | --------------------------------------- |
| `GET`  | `/v1/setup/status`         | Get setup status and installed features |
| `POST` | `/v1/setup/install`        | Install optional features (batch)       |
| `POST` | `/v1/setup/skip`           | Mark setup wizard complete              |
| `GET`  | `/v1/setup/install/events` | Stream install progress via SSE         |
| `GET`  | `/v1/setup/db/status`      | Check database migration status         |
| `POST` | `/v1/setup/db/migrate`     | Run database migrations                 |

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
    "stream": false,
    "agent_mode": false,
    "agent_role": "knowledge|maintainer"
  },
  "conversation_id": "optional-conversation-id"
}
```

## Documents

| Method   | Endpoint                                        | Description                                          |
| -------- | ----------------------------------------------- | ---------------------------------------------------- |
| `POST`   | `/v1/documents`                                 | Upload document for ingestion (returns 202 Accepted) |
| `GET`    | `/v1/documents`                                 | List all documents (supports pagination)             |
| `PATCH`  | `/v1/documents/{document_id}`                   | Update document metadata                             |
| `GET`    | `/v1/documents/{document_id}`                   | Get document details including enrichment data       |
| `DELETE` | `/v1/documents/{document_id}`                   | Delete a document                                    |
| `GET`    | `/v1/documents/{document_id}/file`              | Download original document file                      |
| `GET`    | `/v1/documents/{document_id}/events`            | Stream document processing events via SSE            |
| `GET`    | `/v1/documents/{document_id}/chunks`            | Get document chunks                                  |
| `PUT`    | `/v1/documents/{document_id}/chunks/{chunk_id}` | Update a chunk and regenerate embeddings             |
| `DELETE` | `/v1/documents/{document_id}/chunks/{chunk_id}` | Delete a chunk                                       |
| `GET`    | `/v1/documents/{document_id}/entities`          | Get extracted entities with pagination               |
| `GET`    | `/v1/documents/{document_id}/relationships`     | Get entity relationships with pagination             |
| `GET`    | `/v1/documents/{document_id}/similarities`      | Get similarity relationships between chunks          |
| `GET`    | `/v1/documents/{document_id}/communities`       | Get entity clusters/communities                      |
| `GET`    | `/v1/documents/{document_id}/subgraph`          | Get the document-scoped knowledge subgraph       |
| `GET`    | `/v1/documents/{document_id}/shares`            | List tenant targets that can access a shared document (super_admin / default tenant admin) |
| `POST`   | `/v1/documents/{document_id}/shares`            | Add tenant targets to a document share list          |
| `PUT`    | `/v1/documents/{document_id}/shares`            | Replace all tenant targets on a document share list  |
| `DELETE` | `/v1/documents/{document_id}/shares`            | Remove tenant targets from a document share list     |

### Document Upload

```bash
curl -X POST /v1/documents \
  -H "X-API-Key: your-key" \
  -F "file=@document.pdf" \
  -F "tenant_id=default"
```

## Communities

| Method | Endpoint                  | Description                                   |
| ------ | ------------------------- | --------------------------------------------- |
| `GET`  | `/v1/communities`         | List communities for the current tenant       |
| `GET`  | `/v1/communities/{id}`    | Get community details                         |
| `POST` | `/v1/communities/refresh` | Trigger community detection and summarization |

## Connectors

| Method | Endpoint                                 | Description               |
| ------ | ---------------------------------------- | ------------------------- |
| `GET`  | `/v1/connectors`                         | List available connectors |
| `GET`  | `/v1/connectors/{connector_type}/status` | Get connector status      |
| `POST` | `/v1/connectors/{connector_type}/auth`   | Authenticate a connector  |
| `POST` | `/v1/connectors/{connector_type}/sync`   | Trigger connector sync    |
| `GET`  | `/v1/connectors/{connector_type}/items`  | Browse connector items    |
| `POST` | `/v1/connectors/{connector_type}/ingest` | Ingest selected items     |

> See [CONNECTORS.md](./CONNECTORS.md) for detailed connector documentation.

## Feedback

| Method | Endpoint                    | Description                          |
| ------ | --------------------------- | ------------------------------------ |
| `POST` | `/v1/feedback`              | Submit feedback for a query response |
| `GET`  | `/v1/feedback/{request_id}` | Get feedback for a specific request  |

> See [FEEDBACK_SYSTEM.md](./FEEDBACK_SYSTEM.md) for detailed feedback documentation.

## Export

| Method   | Endpoint                                    | Description                             |
| -------- | ------------------------------------------- | --------------------------------------- |
| `GET`    | `/v1/export/conversation/{conversation_id}` | Export a single conversation (ZIP)      |
| `POST`   | `/v1/export/all`                            | Start async export of all conversations |
| `GET`    | `/v1/export/job/{job_id}`                   | Get export job status                   |
| `GET`    | `/v1/export/job/{job_id}/download`          | Download completed export               |
| `DELETE` | `/v1/export/job/{job_id}`                   | Cancel/delete export job                |

## Folders

| Method   | Endpoint                  | Description         |
| -------- | ------------------------- | ------------------- |
| `GET`    | `/v1/folders`             | List all folders    |
| `GET`    | `/v1/folders/counts`      | Get document counts per folder |
| `POST`   | `/v1/folders`             | Create a new folder |
| `DELETE` | `/v1/folders/{folder_id}` | Delete a folder     |

## Graph Editor

| Method   | Endpoint                          | Description                           |
| -------- | --------------------------------- | ------------------------------------- |
| `GET`    | `/v1/graph/editor/top`            | List top connected nodes              |
| `GET`    | `/v1/graph/editor/search`         | Search nodes by name/description      |
| `GET`    | `/v1/graph/editor/neighborhood`   | Get node neighborhood (nodes + edges) |
| `POST`   | `/v1/graph/editor/heal`           | Suggest connections for a node        |
| `POST`   | `/v1/graph/editor/nodes/merge`    | Merge nodes                           |
| `POST`   | `/v1/graph/editor/edge`           | Create an edge                        |
| `DELETE` | `/v1/graph/editor/edge`           | Delete an edge                        |
| `DELETE` | `/v1/graph/editor/node/{node_id}` | Delete a node                         |
| `GET`    | `/v1/graph/editor/health`         | Graph health summary (orphans, dup candidates) |
| `GET`    | `/v1/graph/editor/anomalies`      | List graph anomalies for review       |
| `POST`   | `/v1/graph/editor/bulk-prune`     | Bulk-prune nodes/edges by anomaly criteria |

## Graph History

| Method   | Endpoint                            | Description                  |
| -------- | ----------------------------------- | ---------------------------- |
| `GET`    | `/v1/graph/history`                 | List graph edit history      |
| `GET`    | `/v1/graph/history/pending/count`   | Get count of pending edits   |
| `POST`   | `/v1/graph/history`                 | Create a pending edit        |
| `POST`   | `/v1/graph/history/{edit_id}/apply` | Apply a pending edit         |
| `POST`   | `/v1/graph/history/{edit_id}/undo`  | Undo an applied edit         |
| `DELETE` | `/v1/graph/history/{edit_id}`       | Reject/delete a pending edit |

## Admin - Jobs

| Method | Endpoint                          | Description                        |
| ------ | --------------------------------- | ---------------------------------- |
| `GET`  | `/v1/admin/jobs`                  | List active and recent tasks       |
| `GET`  | `/v1/admin/jobs/{task_id}`        | Get task details and status        |
| `POST` | `/v1/admin/jobs/{task_id}/cancel` | Cancel or revoke a task            |
| `GET`  | `/v1/admin/jobs/queues/status`    | Get queue depths and worker status |
| `POST` | `/v1/admin/jobs/cancel-all`       | Cancel all active/pending tasks    |

### Job Status Values

- `PENDING` - Task is waiting in queue
- `STARTED` - Task has begun execution
- `PROGRESS` - Task is running with progress updates
- `SUCCESS` - Task completed successfully
- `FAILURE` - Task failed with error
- `REVOKED` - Task was cancelled
- `RETRY` - Task is being retried

## Admin - Configuration

| Method | Endpoint                                     | Description                     |
| ------ | -------------------------------------------- | ------------------------------- |
| `GET`  | `/v1/admin/config/schema`                    | Get configuration schema        |
| `GET`  | `/v1/admin/config/llm-steps`                 | List per-step LLM model assignments |
| `GET`  | `/v1/admin/config/prompts/defaults`          | Get default prompts             |
| `GET`  | `/v1/admin/config/tenants/{tenant_id}`       | Get tenant configuration        |
| `PUT`  | `/v1/admin/config/tenants/{tenant_id}`       | Update tenant configuration     |
| `POST` | `/v1/admin/config/tenants/{tenant_id}/reset` | Reset tenant config to defaults |
| `POST` | `/v1/admin/config/tenants/backfill-active-collection` | Backfill missing active vector collections (super admin) |

### Configurable Parameters

| Parameter                    | Type    | Default                  | Description                      |
| ---------------------------- | ------- | ------------------------ | -------------------------------- |
| `top_k`                      | integer | 10                       | Max chunks to retrieve           |
| `expansion_depth`            | integer | 2                        | Graph traversal depth            |
| `similarity_threshold`       | float   | 0.7                      | Minimum similarity score         |
| `reranking_enabled`          | boolean | true                     | Enable reranking                 |
| `hyde_enabled`               | boolean | false                    | Enable HyDE embeddings           |
| `graph_expansion_enabled`    | boolean | true                     | Enable graph expansion           |
| `llm_provider`               | string  | `openai`                 | LLM provider                     |
| `llm_model`                  | string  | `gpt-4o-mini`            | LLM model                        |
| `embedding_provider`         | string  | `openai`                 | Embedding provider               |
| `embedding_model`            | string  | `text-embedding-3-small` | Embedding model                  |
| `active_vector_collection`   | string  | `amber_default`          | Active Milvus collection (super admin only) |
| `hybrid_ocr_enabled`         | boolean | true                     | Enable OCR for image-heavy pages |
| `ocr_text_density_threshold` | integer | 50                       | OCR trigger threshold            |
| `rag_system_prompt`          | string  | null                     | Override system prompt           |
| `rag_user_prompt`            | string  | null                     | Override user prompt             |

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

## Admin - Maintenance

| Method   | Endpoint                                                      | Description                          |
| -------- | ------------------------------------------------------------- | ------------------------------------ |
| `GET`    | `/v1/admin/maintenance/metrics/queries`                       | List recent query metrics            |
| `GET`    | `/v1/admin/maintenance/stats`                                 | Get comprehensive system statistics  |
| `POST`   | `/v1/admin/maintenance/cache/clear`                           | Clear Redis cache (optional pattern) |
| `POST`   | `/v1/admin/maintenance/prune/orphans`                         | Remove orphan graph nodes            |
| `POST`   | `/v1/admin/maintenance/prune/stale-communities`               | Remove old community summaries       |
| `GET`    | `/v1/admin/maintenance/reconciliation`                        | Get dual-write sync status           |
| `POST`   | `/v1/admin/maintenance/reindex`                               | Trigger vector index rebuild         |
| `GET`    | `/v1/admin/maintenance/vectors/collections`                   | Get Milvus collection details        |
| `DELETE` | `/v1/admin/maintenance/vectors/collections/{collection_name}` | Delete a Milvus collection           |

## Admin - Chat History

> Requires `super_admin` scope. Conversation content is redacted for
> conversations without user feedback (see [TENANT_SECURITY.md](./TENANT_SECURITY.md)).

| Method   | Endpoint                              | Description                    |
| -------- | ------------------------------------- | ------------------------------ |
| `GET`    | `/v1/admin/chat/history`              | List recent chat conversations |
| `GET`    | `/v1/admin/chat/history/{request_id}` | Get full conversation details  |
| `DELETE` | `/v1/admin/chat/history/{request_id}` | Delete a conversation          |

## Admin - Ragas Benchmarks

| Method   | Endpoint                              | Description                        |
| -------- | ------------------------------------- | ---------------------------------- |
| `GET`    | `/v1/admin/ragas/stats`               | Get overall benchmark statistics   |
| `GET`    | `/v1/admin/ragas/datasets`            | List available golden datasets     |
| `POST`   | `/v1/admin/ragas/datasets`            | Upload new golden dataset (JSON)   |
| `DELETE` | `/v1/admin/ragas/datasets/{filename}` | Delete a dataset                   |
| `POST`   | `/v1/admin/ragas/run-benchmark`       | Trigger benchmark run              |
| `GET`    | `/v1/admin/ragas/job/{job_id}`        | Get benchmark run status/results   |
| `GET`    | `/v1/admin/ragas/comparison`          | Compare multiple benchmark runs    |
| `GET`    | `/v1/admin/ragas/runs`                | List benchmark runs with filtering |
| `DELETE` | `/v1/admin/ragas/runs/{run_id}`       | Delete a benchmark run             |

## Admin - Keys

| Method   | Endpoint                                      | Description             |
| -------- | --------------------------------------------- | ----------------------- |
| `GET`    | `/v1/admin/keys/me`                           | Get current key details |
| `GET`    | `/v1/admin/keys`                              | List API keys           |
| `POST`   | `/v1/admin/keys`                              | Create API key          |
| `PATCH`  | `/v1/admin/keys/{key_id}`                     | Update API key          |
| `DELETE` | `/v1/admin/keys/{key_id}`                     | Revoke/delete API key   |
| `POST`   | `/v1/admin/keys/{key_id}/tenants`             | Assign key to tenant    |
| `DELETE` | `/v1/admin/keys/{key_id}/tenants/{tenant_id}` | Remove tenant access    |

## Admin - Tenants

| Method   | Endpoint                        | Description        |
| -------- | ------------------------------- | ------------------ |
| `GET`    | `/v1/admin/tenants`             | List tenants       |
| `POST`   | `/v1/admin/tenants`             | Create tenant      |
| `GET`    | `/v1/admin/tenants/{tenant_id}` | Get tenant details |
| `PATCH`  | `/v1/admin/tenants/{tenant_id}` | Update tenant      |
| `DELETE` | `/v1/admin/tenants/{tenant_id}` | Delete tenant      |

## Admin - Feedback

| Method   | Endpoint                                         | Description                          |
| -------- | ------------------------------------------------ | ------------------------------------ |
| `GET`    | `/v1/admin/feedback/pending`                     | List pending feedback                |
| `POST`   | `/v1/admin/feedback/{feedback_id}/verify`        | Verify feedback (promote to library) |
| `POST`   | `/v1/admin/feedback/{feedback_id}/reject`        | Reject feedback                      |
| `GET`    | `/v1/admin/feedback/approved`                    | List verified feedback               |
| `PUT`    | `/v1/admin/feedback/{feedback_id}/toggle-active` | Activate/deactivate a Q&A pair       |
| `DELETE` | `/v1/admin/feedback/{feedback_id}`               | Delete feedback                      |
| `GET`    | `/v1/admin/feedback/export`                      | Export verified feedback (JSONL)     |

## Admin - Rules

| Method   | Endpoint                    | Description       |
| -------- | --------------------------- | ----------------- |
| `GET`    | `/v1/admin/rules`           | List global rules |
| `POST`   | `/v1/admin/rules`           | Create rule       |
| `PUT`    | `/v1/admin/rules/{rule_id}` | Update rule       |
| `DELETE` | `/v1/admin/rules/{rule_id}` | Delete rule       |
| `POST`   | `/v1/admin/rules/upload`    | Upload rules file |

## Admin - Context Graph

| Method   | Endpoint                                          | Description                         |
| -------- | ------------------------------------------------- | ----------------------------------- |
| `GET`    | `/v1/admin/context-graph/stats`                   | Get context graph stats             |
| `GET`    | `/v1/admin/context-graph/feedback`                | List feedback nodes                 |
| `DELETE` | `/v1/admin/context-graph/feedback/{feedback_id}`  | Delete feedback node                |
| `GET`    | `/v1/admin/context-graph/chunk/{chunk_id}/impact` | Get feedback impact for a chunk     |
| `GET`    | `/v1/admin/context-graph/conversations`           | List conversations in context graph |

## Admin - Retention

| Method   | Endpoint                                     | Description                   |
| -------- | -------------------------------------------- | ----------------------------- |
| `GET`    | `/v1/admin/retention/facts`                  | List stored user facts        |
| `DELETE` | `/v1/admin/retention/facts/{fact_id}`        | Delete a user fact            |
| `GET`    | `/v1/admin/retention/summaries`              | List conversation summaries   |
| `DELETE` | `/v1/admin/retention/summaries/{summary_id}` | Delete a conversation summary |

## Admin - Embeddings

| Method | Endpoint                                | Description                     |
| ------ | --------------------------------------- | ------------------------------- |
| `GET`  | `/v1/admin/embeddings/check`            | Check embedding compatibility   |
| `POST` | `/v1/admin/embeddings/migrate`          | Run embedding migration         |
| `GET`  | `/v1/admin/embeddings/migration-status` | Get migration status            |
| `POST` | `/v1/admin/embeddings/cancel-migration` | Cancel an in-progress migration |

## Admin - Providers

| Method | Endpoint                        | Description                    |
| ------ | ------------------------------- | ------------------------------ |
| `GET`  | `/v1/admin/providers/available` | List available model providers |
| `POST` | `/v1/admin/providers/validate`  | Validate provider credentials  |
| `POST` | `/v1/admin/providers/ollama/test-connection` | Test Ollama endpoint reachability |

## Admin - Seed Data

| Method | Endpoint                     | Description           |
| ------ | ---------------------------- | --------------------- |
| `POST` | `/v1/admin/seed-sample-data` | Seed sample documents |
| `GET`  | `/v1/admin/sample-datasets`  | List bundled sample datasets |

## Authentication Ticket

| Method | Endpoint          | Description                                               |
| ------ | ----------------- | -------------------------------------------------------- |
| `POST` | `/v1/auth/ticket` | Issue a short-lived ticket for SSE/stream authentication |

## Chat History (User)

> User-facing conversation history for the authenticated key. Distinct from the admin chat history under `/v1/admin/chat/*`.

| Method   | Endpoint                             | Description                      |
| -------- | ------------------------------------ | -------------------------------- |
| `GET`    | `/v1/chat/history`                   | List the caller conversations    |
| `GET`    | `/v1/chat/history/{conversation_id}` | Get a conversation full detail   |
| `DELETE` | `/v1/chat/history/{conversation_id}` | Delete a conversation            |

## Groups

> Groups bind API keys (members) and folders to control access to shared collections.

| Method   | Endpoint                                     | Description                     |
| -------- | -------------------------------------------- | ------------------------------- |
| `GET`    | `/v1/groups`                                 | List groups                     |
| `POST`   | `/v1/groups`                                 | Create a group                  |
| `GET`    | `/v1/groups/{group_id}`                      | Get group details               |
| `PATCH`  | `/v1/groups/{group_id}`                      | Update a group                  |
| `DELETE` | `/v1/groups/{group_id}`                      | Delete a group                  |
| `GET`    | `/v1/groups/{group_id}/members`              | List group members (API keys)   |
| `POST`   | `/v1/groups/{group_id}/members`              | Add a member to the group       |
| `DELETE` | `/v1/groups/{group_id}/members/{api_key_id}` | Remove a member                 |
| `GET`    | `/v1/groups/{group_id}/folders`              | List folders bound to the group |
| `POST`   | `/v1/groups/{group_id}/folders`              | Bind a folder to the group      |
| `DELETE` | `/v1/groups/{group_id}/folders/{folder_id}`  | Unbind a folder                 |
| `GET`    | `/v1/me/groups`                              | List groups for the current key |

## Admin - Backup

> Requires `super_admin` scope. See [disaster_recovery_runbook.md](./disaster_recovery_runbook.md).

| Method   | Endpoint                                 | Description                    |
| -------- | ---------------------------------------- | ------------------------------ |
| `POST`   | `/v1/admin/backup/create`                | Start a backup job             |
| `GET`    | `/v1/admin/backup/list`                  | List available backups         |
| `GET`    | `/v1/admin/backup/job/{job_id}`          | Get backup job status          |
| `GET`    | `/v1/admin/backup/job/{job_id}/download` | Download a completed backup    |
| `DELETE` | `/v1/admin/backup/job/{job_id}`          | Delete a backup job/artifact   |
| `POST`   | `/v1/admin/backup/restore`               | Start a restore job            |
| `GET`    | `/v1/admin/backup/restore/{job_id}`      | Get restore job status         |
| `GET`    | `/v1/admin/backup/schedule`              | Get scheduled backup config    |
| `POST`   | `/v1/admin/backup/schedule`              | Create/update scheduled backup |
| `DELETE` | `/v1/admin/backup/schedule`              | Remove scheduled backup        |

## Admin - Observability

> Requires `super_admin` scope. Metrics, deep health, token usage and document-share auditing.

| Method | Endpoint                                          | Description                            |
| ------ | ------------------------------------------------- | -------------------------------------- |
| `GET`  | `/v1/admin/observability/metrics/aggregated`      | Aggregated query metrics over a period |
| `GET`  | `/v1/admin/observability/metrics/recent`          | Recent query metrics                   |
| `GET`  | `/v1/admin/observability/usage/tokens`            | Token usage / cost breakdown           |
| `GET`  | `/v1/admin/observability/health/deep`             | Deep dependency health check           |
| `GET`  | `/v1/admin/observability/document-shares/summary` | Cross-tenant document share summary    |
| `GET`  | `/v1/admin/observability/document-shares/audit`   | Document share audit log               |
| `GET`  | `/v1/admin/observability/taxonomy/corpus-summary` | Corpus taxonomy summary                |

## Admin - Provisioning

> Requires `super_admin` scope. Async tenant provisioning (seed config + vector collections).

| Method   | Endpoint                                                 | Description                         |
| -------- | -------------------------------------------------------- | ----------------------------------- |
| `POST`   | `/v1/admin/provisioning/tenants/{target_tenant_id}`      | Start provisioning a tenant         |
| `GET`    | `/v1/admin/provisioning/tenants/{target_tenant_id}/jobs` | List provisioning jobs for a tenant |
| `GET`    | `/v1/admin/provisioning/jobs/{job_id}`                   | Get provisioning job status         |
| `DELETE` | `/v1/admin/provisioning/jobs/{job_id}`                   | Cancel a provisioning job           |

## Response Codes

| Code  | Description                                |
| ----- | ------------------------------------------ |
| `200` | Success                                    |
| `202` | Accepted (async operation started)         |
| `204` | No Content (successful deletion)           |
| `400` | Bad Request                                |
| `401` | Unauthorized (missing/invalid API key)     |
| `403` | Forbidden (insufficient permissions)       |
| `404` | Not Found                                  |
| `409` | Conflict                                   |
| `413` | Payload Too Large                          |
| `428` | Precondition Required                      |
| `429` | Too Many Requests                          |
| `422` | Validation Error                           |
| `500` | Internal Server Error                      |
| `503` | Service Unavailable (dependency unhealthy) |

## OpenAPI Specification

The complete OpenAPI 3.1 specification is available at:

- **Interactive Docs**: `/docs` (Swagger UI)
- **ReDoc**: `/redoc`
- **JSON Spec**: `/openapi.json`
