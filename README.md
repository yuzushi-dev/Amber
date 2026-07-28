# Amber 

<img width="1533" height="447" alt="amber_avatar" src="https://github.com/user-attachments/assets/102873b7-5bc6-4a91-b688-3ef565d7c0d6" />

> **Preserving Context, Revealing Insight**

Amber answers questions over a document collection by combining vector search with a knowledge graph built from those same documents. It ingests your files, extracts entities and relationships into Neo4j, embeds the chunks into Milvus, and picks a retrieval strategy per query. Every answer comes back with citations to the chunks it was built from.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/badge/release-v1.3.0-blue.svg)](https://github.com/yuzushi-dev/Amber/releases)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/react-19-blue.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688.svg)](https://fastapi.tiangolo.com)

## Table of Contents

- [Overview](#overview)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [How It Works](#how-it-works)
- [API Reference](#api-reference)
- [Application Structure](#application-structure)
- [Development](#development)
- [Testing](#testing)
- [Performance & Scaling](#performance--scaling)
- [Troubleshooting](#troubleshooting)
- [Implementation Details](#implementation-details)
- [Contributing](#contributing)
- [License](#license)

## Overview

A plain RAG system retrieves chunks by vector similarity alone. That works until the answer depends on how things in the corpus relate to each other, and then it quietly returns the wrong five chunks. Amber builds that structure explicitly instead of hoping the embeddings encode it.

At ingestion, each document is chunked, embedded into Milvus, passed to an LLM that extracts entities and relationships into Neo4j, and the resulting entity graph is clustered into communities with the hierarchical Leiden algorithm. At query time, any of those layers can be searched, and usually more than one is.

Five retrieval modes:

- **Basic**: vector-only search, for simple queries
- **Local**: entity-focused graph traversal, for precise lookups
- **Global**: map-reduce over community summaries, for broad questions
- **Drift**: iterative reasoning with generated follow-up questions, for complex queries
- **Structured**: direct Cypher execution, for list and count queries

## Getting Started

### Prerequisites

- **Docker & Docker Compose v2.20+** - Recommended for easiest setup
- **LLM Provider** - At least one required:
  - [OpenAI](https://platform.openai.com/) - GPT models (cloud)
  - [Anthropic](https://console.anthropic.com/) - Claude models (cloud)
  - [Ollama](https://ollama.com/) - Local models, no API key needed
- **System Resources** - Minimum:
  - 8 GB RAM (16 GB recommended)
  - 20 GB disk space
  - 2 CPU cores (4+ recommended)

### Quick Start (Docker - Recommended)

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yuzushi-dev/Amber.git
   cd Amber
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set your API keys:
   ```ini
   # LLM Provider (required - choose at least one)
   OPENAI_API_KEY=sk-proj-...
   ANTHROPIC_API_KEY=sk-ant-...

   # Security (important!)
   SECRET_KEY=your-secret-key-here  # Generate with: openssl rand -hex 32
   NEO4J_PASSWORD=strong_neo4j_password

   # Optional: Customize ports
   API_PORT=8000
   ```

3. **Launch Services**
   ```bash
   # Standard launch (CPU mode)
   ./start.sh
   
   # With NVIDIA GPU support (for local embeddings/models)
   ./start.sh --gpu
   
   # Or manually:
   # docker compose up -d
   # docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d  # GPU
   ```

   This starts 10 services:
   - `nginx` - Edge proxy on ports 8000 and 3000, owns all external traffic
   - `api` - FastAPI backend (internal; exposed through nginx)
   - `frontend` - React frontend (internal; served through nginx)
   - `worker` - Celery workers
   - `postgres` - Metadata database (host port 5433 → container 5432)
   - `neo4j` - Graph database (ports 7474, 7687)
   - `milvus` - Vector database (port 19530)
   - `etcd` - Milvus metadata store (internal)
   - `redis` - Cache & broker (port 6379)
   - `garage` - Object storage, S3 API (port 3900), Admin API (port 3903)

   > **Note:** nginx owns host ports `:8000` and `:3000`. The API and frontend containers do not bind host ports directly. For a zero-downtime deploy, `deploy/docker-compose.canary.yml` brings up an `api-canary` container on port 8001, which you can smoke-test without nginx in the path; `deploy/cutover.sh --to canary` then repoints nginx at it, `--dry-run` shows the change first, and `--to live` rolls back.

4. **Run Database Migrations** (Critical!)
   ```bash
   make migrate
   # or: docker compose exec api alembic upgrade head
   ```

5. **Access the Application**
   - **Frontend**: [http://localhost:3000](http://localhost:3000) (served by nginx; the frontend container runs `npm run dev` automatically)
   - **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Neo4j Browser**: [http://localhost:7474](http://localhost:7474)
     - Username: `neo4j`
     - Password: (from `.env` `NEO4J_PASSWORD`)
   - **Garage Admin API**: [http://localhost:3903](http://localhost:3903)
     - Credentials: (from `.env` `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY`)

6. **Verify Health**
   ```bash
   curl http://localhost:8000/health
   # Should return: {"status": "healthy"}
   ```

7. **Generate an API Key**
   ```bash
   make generate-key
   # or: docker compose exec api python -c "from src.shared.security import generate_api_key; print(generate_api_key())"
   ```

   Save the generated key - you'll need it for API requests.

### First Steps

1. **Upload Your First Document** (via API)
   ```bash
   curl -X POST "http://localhost:8000/v1/documents" \
     -H "X-API-Key: your-api-key-here" \
     -F "file=@path/to/document.pdf"
   ```

2. **Check Processing Status**
   ```bash
   curl "http://localhost:8000/v1/documents/{document_id}/status" \
     -H "X-API-Key: your-api-key-here"
   ```

3. **Query the Knowledge Base**
   ```bash
   curl -X POST "http://localhost:8000/v1/query" \
     -H "X-API-Key: your-api-key-here" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "What are the main topics in my documents?",
       "options": {
         "search_mode": "basic",
         "include_sources": true
       }
     }'
   ```

## Configuration

### Environment Variables

Key configuration options in `.env`:

#### Core Settings
```ini
# Application
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=false
LOG_LEVEL=INFO

# Security
SECRET_KEY=your-secret-key-here

# Set to false once every API key has explicit tenant links, so that an
# unlinked key is rejected instead of falling back to the default tenant
ALLOW_LINKLESS_KEY_DEFAULT_TENANT=true
```

#### Database Connections
```ini
# PostgreSQL
DATABASE_URL=postgresql+asyncpg://graphrag:graphrag@postgres:5432/graphrag
POSTGRES_USER=graphrag
POSTGRES_PASSWORD=graphrag
POSTGRES_DB=graphrag

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme

# Milvus
MILVUS_HOST=milvus
MILVUS_PORT=19530

# Garage (S3-compatible object storage)
OBJECT_STORAGE_ACCESS_KEY=your-garage-access-key
OBJECT_STORAGE_SECRET_KEY=your-garage-secret-key

# Redis
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
```

#### LLM Providers
```ini
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_LLM_PROVIDER=openai   # openai | anthropic | ollama
DEFAULT_LLM_MODEL=gpt-4o-mini

DEFAULT_EMBEDDING_PROVIDER=openai   # openai | ollama | local
DEFAULT_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

#### Ollama (local LLMs, no cloud key required)
```ini
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2

# Context window — increase for large RAG prompts
OLLAMA_NUM_CTX=32768

# Concurrent-request capacity guard (prevents GPU OOM under load)
OLLAMA_CAPACITY_ENABLED=true
OLLAMA_CAPACITY_TOTAL=6
OLLAMA_CAPACITY_RESERVED_CHAT=2
OLLAMA_CAPACITY_RESERVED_INGESTION=2
```

#### Rate Limiting
```ini
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_REQUESTS_PER_HOUR=1000
RATE_LIMIT_QUERIES_PER_MINUTE=20
RATE_LIMIT_UPLOADS_PER_HOUR=50
```

#### Security & Isolation (v1.1.0+)
```ini
# Application DB role — enforces Row-Level Security (non-superuser)
# Docker network name required (not localhost); omit to fall back to superuser connection
APP_DATABASE_URL=postgresql+asyncpg://graphrag_app:<password>@postgres:5432/graphrag

# Secret key rotation — set OLD value during rotation window, then remove after
SECRET_KEY_OLD=previous-secret-key-here

# LLM capacity guard behaviour (default: fail-closed; set true to allow requests through when Redis is absent)
LLM_CAPACITY_FAIL_OPEN=false
```

## Usage

### Document Upload

```python
import requests

url = "http://localhost:8000/v1/documents"
headers = {"X-API-Key": "your-api-key"}
files = {"file": open("report.pdf", "rb")}

response = requests.post(url, headers=headers, files=files)
print(response.json())
```

### Querying

#### Basic Query
```python
payload = {
    "query": "What are the key findings?",
    "options": {
        "search_mode": "basic",
        "include_sources": true
    }
}

response = requests.post(
    "http://localhost:8000/v1/query",
    headers={"X-API-Key": "your-api-key"},
    json=payload
)
```

#### Advanced Search Modes
```python
# Local search - entity-focused
payload = {"query": "...", "options": {"search_mode": "local"}}

# Global search - community summaries
payload = {"query": "...", "options": {"search_mode": "global"}}

# Drift search - iterative reasoning
payload = {"query": "...", "options": {"search_mode": "drift"}}
```

#### Streaming
```bash
curl -N "http://localhost:8000/v1/query/stream?query=Explain..." \
  -H "X-API-Key: your-api-key"
```

## Key Features

### Retrieval

Every mode below is reachable per query, either by naming it explicitly or by letting the router pick one.

#### Vector & Hybrid Search (Basic Mode)
- **Hybrid Retrieval**: Combines dense (semantic) and sparse (SPLADE) vectors, so keyword matches and paraphrases both land
- **Dense**: Text-embedding-3-small embeddings (1536 dimensions)
- **Sparse (New)**: Learned keyword expansion using SPLADE (cocondenser-ensembledistil)
- **Native Fusion**: Uses Reciprocal Rank Fusion (RRFRanker) in Milvus
- Result caching with Redis for performance

#### Graph-Enhanced Retrieval
- **Local Search**: Entity-focused traversal for precise information
- **Global Search**: Hierarchical community summaries for broad questions
- **Drift Search**: Agentic, iterative exploration with dynamic follow-up questions
- **Graph Traversal**: Multi-hop relationship exploration

#### Query Processing
- **Query Rewriting**: Improves ambiguous or poorly-formed queries
- **Query Decomposition**: Breaks complex questions into sub-queries
- **HyDE (Hypothetical Document Embeddings)**: Generates hypothetical answers to improve retrieval
- **Query Routing**: Automatically selects the best search strategy
- **Structured Query Detection**: Bypasses RAG for simple list/count queries

#### Document Taxonomy & Audience Routing
- **Automatic Classification**: Documents stamped with a taxonomy label (`AdminGuide`, `CEGuide`, `UserGuide`, `ZendeskKB`) at ingestion time based on folder name and keyword heuristics
- **Product Context Resolution**: Deterministic `ProductContextResolver` maps CE/admin/user terminology in the query to edition and audience, with no LLM call
- **Taxonomy-Aware Retrieval**: Pre-filters the candidate pool by taxonomy before vector/graph search, with a 4-stage broadening fallback (strict → edition-only → audience-only → unfiltered) to guarantee recall
- **Observability**: Taxonomy routing decisions are recorded in the execution trace and surfaced through the observability admin endpoint
- **Backfill Script**: `scripts/backfill_document_taxonomy.py` re-classifies existing documents without re-ingestion

### Knowledge Graph

Entities and relations are extracted per chunk, deduplicated, then clustered into communities that can be summarized and searched on their own.

#### Entity & Relationship Extraction
- **LLM-powered extraction** from document chunks
- **Gleaning**: Iterative extraction to maximize recall
- Supports multiple entity types and relationship patterns
- Automatic entity deduplication and linking

#### Community Detection
- **Hierarchical Leiden Algorithm** for multi-level clustering
- Configurable resolution for cluster granularity
- Automatic community summarization using LLMs
- Community embedding for similarity search

#### Graph Management
- **Incremental updates** without full rebuilds
- **Maintenance operations**: deduplication, enrichment, summarization
- **Graph statistics** and health monitoring
- **Tenant isolation** for multi-tenant deployments

#### Shared GraphRAG & Document ACL
- **Shared Corpus**: `default` tenant acts as the enterprise knowledge base; other tenants consume shared content without duplication via explicit ACL grants
- **ACL-Enforced Retrieval**: Vector search, graph traversal, and global search all filter by document-share visibility; non-shared `default` documents are invisible to other tenants
- **Document Shares API**: Share documents to specific tenants at upload time or via the document library; bulk workflows available in the admin UI
- **Short-Lived Cache**: Visible shared document ID set is cached in Redis with explicit invalidation on share mutations for low-latency ACL checks
- **Runtime Kill Switches**: Operators can independently disable share management, vector ACL, or graph ACL without a code deployment

### Document Processing

Everything between an uploaded file and a queryable chunk runs in Celery, with the document's state tracked in Postgres so a crashed worker does not lose the job.

#### Multi-Format Support
- **PDF**: PyMuPDF4LLM, Marker-PDF, and Unstructured fallback
- **Markdown**: Native parsing with structure preservation
- **Text**: Direct ingestion
- **External Sources**: Connectors for Confluence, Zendesk

#### Intelligent Chunking
- **Semantic Chunking**: Respects document structure (headers, paragraphs, code blocks)
- **Configurable Parameters**: Chunk size, overlap, and strategy
- **Token-aware**: Uses tiktoken for accurate token counting
- Preserves document hierarchy and context

#### Background Processing
- **Celery Workers**: Async task processing with Redis broker
- **State Machine**: Tracks document status through pipeline stages
- **Automatic Retries**: Exponential backoff with jitter
- **Stale Job Recovery**: Detects and recovers hung or abandoned tasks
- **Progress Tracking**: Real-time status updates

#### Document Deduplication
- **Content-based hashing** (SHA-256)
- Automatic detection of duplicate uploads
- Idempotent ingestion API

### Generation & Quality

Generation is provider-agnostic, streams over SSE when you call the stream endpoint, and attaches per-chunk citations plus a quality score to every answer.

#### Multi-Provider LLM Support
- **OpenAI**: GPT-4o, GPT-4o-mini, GPT-4.1-mini, GPT-4.1-nano, GPT-4-turbo, o1
- **Anthropic**: Claude Sonnet 4, Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus
- **Ollama**: Local LLM support (Llama 3, Mistral, DeepSeek, Phi-3, Qwen, etc.)
- **Tiered Providers**: Economy (extraction), Standard (RAG), Premium (evaluation)
- **Streaming**: Server-Sent Events for real-time token streaming
- **Cost Tracking**: Token usage and cost estimation per query

#### Complexity Routing

- **Deterministic Scorer**: Rates each query plus its retrieved context across 9 dimensions with no LLM call, then assigns a complexity tier (`simple`, `standard`, `complex`, `reasoning`) that selects the Ollama model. This axis is unrelated to the provider tiers above, despite both using the word `standard`
- **Per-Tenant Opt-In**: Off unless enabled for the tenant
- **Observable**: The chosen tier is emitted as a `complexity_tier` SSE event; Ollama thinking mode is available at the reasoning tier

#### Embedding Providers
- **Ollama**: External service (via API). Best for existing Ollama users, GPU offloading, and model flexibility (e.g., `nomic-embed-text`, `mxbai-embed-large`).
- **Local**: Internal native library (`sentence-transformers`). Best for zero-setup, self-contained usage. Runs models like `BAAI/bge-m3` directly within the application (requires ~1-2GB RAM).

#### Citation & Source Grounding
- **Chunk-level citations** with relevance scores
- **Document attribution** with titles and metadata
- **Source deduplication** across retrieval results
- **Preview snippets** for context
- **Interactive Citation Explorer**: Click-through source navigation with highlighting

#### Quality Guardrails
- **Faithfulness checks**: Ensures answers are grounded in sources
- **Relevance scoring**: Filters irrelevant results
- **Follow-up suggestions**: Generates contextual next questions
- **Ragas Integration**: Automated evaluation with standard metrics

#### Response Quality Indicators
- **Quality Badge**: Visual score indicator for response confidence
- **Routing Badge**: Shows which retrieval mode was used (Basic/Local/Global/Drift)
- **Persisted Metrics**: Badges saved with conversation history

#### User Feedback System
- **Thumbs Up/Down**: Direct feedback on AI responses
- **Pending Review Queue**: Admin review of user feedback
- **Q&A Library**: Verified responses for training/fine-tuning
- **Golden Dataset Export**: Export approved Q&A pairs for evaluation

### Admin and Operations

The admin UI covers the operational surface: documents, connectors, jobs, backups, evaluation, and live tuning of retrieval parameters.

#### Document Management (`/admin/data`)
- **Upload Wizard**: Batch upload with drag-and-drop
- **Live Status Tracking**: Real-time ingestion progress
- **Document Details**: View chunks, entities, relationships, communities
- **Database Overview**: Graph statistics and health metrics
- **Vector Store Inspection**: Collection stats and memory usage
- **PDF Viewer**: In-browser PDF viewing with page navigation
- **Conversation Export**: Export chat history as PDF or Markdown

#### External Connectors (`/admin/connectors`)
- **Confluence**: Sync wiki pages from Atlassian Confluence Cloud
- **Zendesk**: Ingest Help Center articles from Zendesk
- **Content Browser**: Browse and selectively ingest items from connected services
- **Incremental Sync**: Efficient updates using `since` timestamps
- See [docs/CONNECTORS.md](docs/CONNECTORS.md) for configuration details

#### Job Management (`/admin/ops`)
- **Job Dashboard**: Monitor active, pending, and completed tasks
- **Job Controls**: Cancel, retry, or view logs for any job
- **Queue Monitoring**: Real-time inspection of Celery queues
- **Worker Health**: Track worker status and task concurrency
- **Stop All Jobs**: Emergency termination of all running tasks

#### Backup & Restore (`/admin/backup`)
- **Full System Backup**: Complete archive of PostgreSQL (metadata), Neo4j (graph), Milvus (vectors), and Garage (files)
- **User Data Backup**: Lightweight portability scope (Vectors, Graph, Chunks) sans system configs
- **Point-in-Time Recovery**: Restore capability with "Merge" or "Replace" strategies
- **Scheduled Backups**: Automated daily/weekly snapshots with retention policies
- **Scripted Backup**: `scripts/backup.sh` covers the whole Garage stack and supports `--dry-run`

#### Maintenance & Operations
- **Community Detection**: Trigger full or incremental updates
- **Graph Enrichment**: Entity resolution and relationship strengthening
- **Index Optimization**: Rebuild vector indices
- **Cache Management**: Clear semantic and result caches
- **System Health**: Health checks across all services

#### Evaluation & Benchmarking
- **Ragas Integration**: Faithfulness, relevance, precision, recall
- **Golden Dataset Management**: Upload and manage test sets
- **Benchmark Execution**: Batch evaluation with progress tracking
- **Results Dashboard**: Visualize scores and trends over time

#### Dynamic Configuration
- **Tuning Dashboard**: Adjust retrieval parameters without restarts
- **Chunking Strategy**: Modify chunk size and overlap
- **Search Settings**: Configure top-k, reranking, and fusion weights
- **Provider Selection**: Switch LLM and embedding providers
- **Global Domain Rules**: Define rules that apply to all queries via Admin UI

### Security & Reliability

Multi-tenancy is enforced at the database layer, not only in application code, and the guards fail closed when Redis is missing.

#### Authentication & Authorization
- **API Key Management**: SHA-256 hashed keys stored in PostgreSQL; tiered scopes (`user`, `tenant_admin`, `super_admin`)
- **Tenant Isolation**: The tenant comes from the API key's links, optionally narrowed by an `X-Tenant-ID` header; asking for a tenant the key is not linked to returns 403. A key with no tenant links at all still falls back to the `default` tenant and logs a warning on every request, a legacy bootstrap path you close with `ALLOW_LINKLESS_KEY_DEFAULT_TENANT=false`
- **DB-Layer RLS**: `FORCE ROW LEVEL SECURITY` on 8 tenant tables via a dedicated `graphrag_app` Postgres role (`NOBYPASSRLS`); workers use a super-admin session flag to bypass legitimately
- **Rate Limiting**: Per-tenant request and upload limits, fail-closed (HTTP 503) when Redis is unavailable
- **Upload Size Limits**: Configurable max file sizes
- **Agent Filesystem Access**: The Maintainer Agent's `read_file`, `list_directory`, and `grep_search` tools are off unless a request explicitly sets `agent_role`; the default Knowledge Agent has graph and vector tools only

#### Secret Management & Credential Security
- **Dual-Secret Keyring**: Zero-downtime `SECRET_KEY` rotation via `SECRET_KEY_OLD` fallback; tokens signed under the old key remain valid during the rotation window
- **Connector Credential Encryption**: OAuth tokens, passwords, and subdomain strings are encrypted at rest with Fernet (AES-128-CBC, key derived from `SECRET_KEY`). They are never stored in plain JSONB
- **SSE Ticket One-Time Use**: Auth tickets consumed atomically via Redis `GETDEL`; replay within the TTL window is no longer possible
- **Exception Sanitization**: HTTP 500 responses no longer include DB hostnames, connection strings, or raw exception text

#### Error Handling & Resilience
- **Circuit Breakers**: Prevent cascade failures
- **Graceful Degradation**: Fallback to simpler modes on errors
- **Retry Logic**: Automatic retries with exponential backoff
- **Structured Logging**: JSON logs with request IDs
- **Health Checks**: Liveness and readiness probes
- **Fail-Closed Capacity Guard**: LLM capacity limiter fails closed when Redis is absent (`LLM_CAPACITY_FAIL_OPEN=false` default)

#### Observability
- **Request Tracing**: Request IDs for end-to-end tracking
- **Timing Metrics**: Per-request timing for every pipeline stage
- **Cache Hit Rates**: Monitor cache effectiveness
- **Query Metrics**: Track input/output tokens, costs, latency breakdowns (retrieval vs generation), and success/error rates per query
- **Taxonomy Routing Metrics**: Per-query taxonomy resolution stage and document pre-filter stats
- **Event Stream**: Real-time processing events via WebSockets
- **Audit Trail**: Config changes and curation actions record the actual caller identity in the audit log

## System Architecture

Amber runs as a set of services behind an nginx edge proxy: a React frontend, a FastAPI API, Celery workers for everything slow, and six data stores that each hold one kind of state (Postgres, Neo4j, Milvus, Redis, Garage, etcd).

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                              │
│  ┌──────────────────────┐      ┌──────────────────────────┐    │
│  │  Consumer Interface  │      │  Admin Dashboard         │    │
│  │  (/amber/chat)       │      │  (/admin/*)              │    │
│  │  - Clean chat UI     │      │  - Document Management   │    │
│  │  - SSE Streaming     │      │  - Job Monitoring        │    │
│  │  - Citation Display  │      │  - System Operations     │    │
│  └──────────────────────┘      └──────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API GATEWAY                               │
│                  FastAPI (Python 3.11+)                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Middleware: Auth, Rate Limit, CORS, Timing, Request ID │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Routes: /query, /documents, /admin/*, /health          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                    ▼                    ▼
┌─────────────────────────────┐  ┌──────────────────────────────┐
│      COMPUTE LAYER          │  │      WORKER LAYER            │
│                             │  │                              │
│  ┌─────────────────────┐   │  │  ┌────────────────────────┐ │
│  │ Retrieval Service   │   │  │  │  Celery Workers        │ │
│  │ - Vector Search     │   │  │  │  - Document Processing │ │
│  │ - Graph Traversal   │   │  │  │  - Entity Extraction   │ │
│  │ - Fusion & Rerank   │   │  │  │  - Graph Construction  │ │
│  └─────────────────────┘   │  │  │  - Community Detection │ │
│                             │  │  └────────────────────────┘ │
│  ┌─────────────────────┐   │  │                              │
│  │ Generation Service  │   │  │  ┌────────────────────────┐ │
│  │ - LLM Orchestration │   │  │  │  Background Tasks      │ │
│  │ - Streaming Support │   │  │  │  - Async Processing    │ │
│  │ - Citation Building │   │  │  │  - State Management    │ │
│  └─────────────────────┘   │  │  │  - Retry Logic         │ │
│                             │  │  └────────────────────────┘ │
└─────────────────────────────┘  └──────────────────────────────┘
                    ▼                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                              │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  PostgreSQL  │  │    Neo4j     │  │    Milvus    │         │
│  │   (Metadata) │  │   (Graph)    │  │   (Vectors)  │         │
│  │              │  │              │  │              │         │
│  │ - Documents  │  │ - Entities   │  │ - Embeddings │         │
│  │ - Chunks     │  │ - Relations  │  │ - Collections│         │
│  │ - Users/Keys │  │ - Communities│  │ - Indices    │         │
│  │ - Jobs       │  │ - Summaries  │  │              │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │    Redis     │  │    Garage    │  │  etcd (Milvus│         │
│  │   (Cache &   │  │   (Object    │  │   metadata)  │         │
│  │    Broker)   │  │   Storage)   │  │              │         │
│  │              │  │              │  │              │         │
│  │ - Embeddings │  │ - Raw Files  │  │ - Config     │         │
│  │ - Results    │  │ - Documents  │  │ - State      │         │
│  │ - Task Queue │  │              │  │              │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      EXTERNAL SERVICES                           │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  OpenAI API      │  │  Anthropic API   │                    │
│  │  - Embeddings    │  │  - Claude Models │                    │
│  │  - GPT Models    │  │                  │                    │
│  └──────────────────┘  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer          | Component        | Technology                | Purpose                                   |
| -------------- | ---------------- | ------------------------- | ----------------------------------------- |
| **Frontend**   | UI Framework     | React 19 + Vite           | Modern reactive UI with fast HMR          |
|                | Router           | TanStack Router v1        | Type-safe routing                         |
|                | State            | Zustand + TanStack Query  | Global state & server state management    |
|                | Styling          | Tailwind CSS + shadcn/ui  | Utility-first CSS with components         |
|                | UI Components    | Radix UI + Framer Motion  | Accessible components with animations     |
|                | Graph Viz        | React Force Graph 2D/3D   | Interactive knowledge graph visualization |
| **API**        | Framework        | FastAPI 0.109+            | High-performance async API                |
|                | Runtime          | Python 3.11+              | Modern Python with type hints             |
|                | Server           | Uvicorn                   | ASGI server with hot reload               |
|                | Validation       | Pydantic v2               | Data validation and serialization         |
| **Databases**  | Metadata         | PostgreSQL 16             | ACID-compliant relational data            |
|                | Graph            | Neo4j 5 Community         | Property graph with Cypher queries        |
|                | Vector           | Milvus 2.5+               | Hybrid search (Dense + Sparse)            |
|                | Cache            | Redis 7                   | In-memory cache & message broker          |
|                | Object Storage   | Garage (S3-compatible)    | S3-compatible file storage                |
|                | Coordination     | etcd                      | Milvus metadata store (internal)          |
| **Processing** | Task Queue       | Celery 5.3+               | Distributed async task processing         |
|                | Broker           | Redis                     | Task queue backend                        |
|                | Migrations       | Alembic                   | Database schema versioning                |
| **External**   | LLM Providers    | OpenAI, Anthropic         | Text generation & embeddings              |
|                | Extraction       | Unstructured, PyMuPDF4LLM | Multi-format document parsing             |
|                | Reranking        | FlashRank                 | Fast semantic reranking                   |
|                | Graph Clustering | igraph + leidenalg        | Community detection                       |
|                | Evaluation       | Ragas                     | RAG metrics evaluation                    |
| **Infra**      | Orchestration    | Docker Compose            | Service orchestration                     |

## How It Works

### 1. Ingestion & Semantic Processing

Ingestion uses structure-aware semantic chunking rather than fixed-size splitting.

*   **Hierarchy-First Splitting**: The `SemanticChunker` (`src/core/ingestion/application/chunking/semantic.py`) respects document anatomy. It protects code blocks first, then splits by:
    1.  **Markdown Headers** (`#`, `##`, ...) to preserve topological context.
    2.  **Paragraphs** (`\n\n`) to maintain flow.
    3.  **Sentences** (via regex) as a last resort for dense text.
*   **Domain-Adaptive Sizing**: Chunk sizes and overlaps are automatically optimized based on document type (defined in `src/core/generation/application/intelligence/strategies.py`):
    *   **General** (Default): 600 tokens / 50 overlap
    *   **Technical** (Code/Manuals): 800 tokens / 50 overlap
    *   **Financial** (Reports/Tables): 800 tokens / 50 overlap
    *   **Scientific** (Research Papers): 1000 tokens / 100 overlap
    *   **Legal** (Contracts/Clauses): 1000 tokens / 100 overlap
    *   **Conversational**: 500 tokens / 100 overlap
*   **Token-Aware Overlap**: Rather than character-based overlap, tokens from the *end* of the previous chunk are prepended to the next to ensure semantic continuity.
*   **Chunk Quality Filtering**: Implements a helper "Quality Coloring" system (`ChunkQualityScorer`) that grades every chunk (0-1) based on text density, fragmentation, and OCR artifacts.
    *   **Noise Reduction**: Low-quality chunks (< 0.3) that also yield zero graph entities are automatically discarded during extraction, preventing "garbage-in" from polluting the vector store.
*   **Resilient Embedding**: The `EmbeddingService` uses exponential backoff retries for rate limits and uses **token-aware batching** (max 8000 tokens/batch) to optimize API throughput.

### 2. Knowledge Graph Construction

Graph construction runs in two stages: iterative entity extraction, then community detection over the extracted entities.

*   **Entity Definition**: Entities are defined via flexible Pydantic models, supporting over 30+ domain-specific types alongside standard named entities.
    *   **Core Types**: `PERSON`, `ORGANIZATION`, `LOCATION`, `EVENT`, `CONCEPT`, `DOCUMENT`, `TECHNOLOGY`, `PRODUCT`, `DATE`, `MONEY`, `ARTICLE`.
    *   **Infrastructure Types**: `COMPONENT`, `SERVICE`, `NODE`, `DOMAIN`, `CLASS_OF_SERVICE`, `RESOURCE`, `QUOTA_OBJECT`, `STORAGE_OBJECT`, `BACKUP_OBJECT`, `ITEM`.
    *   **Operational Types**: `ACCOUNT`, `ACCOUNT_TYPE`, `ROLE`, `TASK`, `PROCEDURE`, `MIGRATION_PROCEDURE`, `CLI_COMMAND`, `API_OBJECT`, `CONFIG_OPTION`, `CERTIFICATE`, `SECURITY_FEATURE`.
    *   **Schema**: Every extracted entity includes a `name` (capitalized), `type`, `description` (self-contained summary).
    *   **Relationships**: `source`, `target`, `type` (e.g., `DEPENDS_ON`, `PROTECTS`, `RUNS_ON`), and `weight` (1-10 strength score).
*   **Generation Mechanism (Dynamic Ontology Injection)**:
    *   The 30+ types are **dynamically injected** into the LLM system prompt as a canonical ontology (`{entity_types_str}`).
    *   The LLM is strictly instructed to classify entities *only* into these allowed types.
    *   **Output Format**: The system uses a strict **Tuple-Delimited Format** (e.g., `("entity"<|>NAME<|>TYPE...)`) to prevent parsing errors common with standard JSON, ensuring high-fidelity extraction even from messy text.
*   **Gleaning (Iterative Extraction)**: Implemented in `GraphExtractor`, this technique prevents "extraction amnesia."
    1.  **Pass 1**: Zero-shot extraction of entities and relationships (Temperature 0.1).
    2.  **Pass 2 (Gleaning)**: The LLM is fed the text *and* the entities found in Pass 1, and asked "What did you miss?". This raises recall on dense documents.
*   **Leiden Community Detection**: We use the hierarchical **Leiden algorithm** to cluster entities into communities.
    *   **Summarization**: Each community is summarized by an LLM to create a "Community Node," enabling **Global Search** (answering "What is the main theme?" by reading summaries rather than thousands of raw chunks).
*   **Quality Assurance (Hybrid Scoring)**: To prevent hallucinations and low-quality extractions, a strict scoring system is applied:
    *   **Intrinsic Confidence**: Entities with an LLM-generated `importance_score < 0.5` are automatically discarded.
    *   **Extrinsic Validation**: A `QualityScorer` module evaluates generated answers and critical extractions on 4 dimensions: **Context Relevance**, **Completeness**, **Factual Grounding**, and **Coherence**, using a mix of LLM evaluation and heuristic checks.

### 3. Advanced Retrieval Logic

Retrieval is handled by an orchestration layer that mixes deterministic and agentic strategies.

*   **Fusion (Hybrid Search)**: We employ **Reciprocal Rank Fusion (RRF)** to combine results from Milvus (Vector) and Neo4j (Keyword/Graph).
    *   **Milvus Hybrid**: Within Milvus itself, we combine **Dense Vectors** (Semantic) and **Sparse Vectors** (SPLADE/Keyword) to find the most relevant chunks.
    *   **Graph Fusion**: These results are then fused with graph traversals.
    *   Formula: `score = Σ(1 / (k + rank + 1))`
    *   This ensures that a document appearing in *both* top-lists is ranked significantly higher than one appearing in only one.
*   **Drift Search (Agentic)**: Defined in `DriftSearchService` (`src/core/retrieval/application/search/drift_search.py`), this is the heaviest retrieval mode:
    1.  **Primer**: Performs an initial standard retrieval (Top-5) to get a baseline context.
    2.  **Expansion Loop**: The LLM analyzes the Primer results and generates **Follow-Up Questions**. These sub-queries are executed to "drift" to related graph neighborhoods.
    3.  **Synthesis**: All accumulated context (Primer + Expansion) is deduplicated and fed to the LLM for a final, citation-backed answer.

### 4. Agentic RAG (ReAct Loop)

For complex queries requiring multi-step reasoning, Amber employs a full **Agentic RAG** architecture using a ReAct (Reason+Act) loop.

*   **Agent Orchestrator**: The `AgentOrchestrator` (`src/core/generation/application/agent/orchestrator.py`) manages the loop:
    1.  Receive query → LLM decides: call a tool OR give final answer.
    2.  If tool: execute, append result to context, repeat.
    3.  Max 10 steps to prevent infinite loops.
*   **Available Tools**:
    | Tool                                         | Description                     | Mode                |
    | -------------------------------------------- | ------------------------------- | ------------------- |
    | `search_codebase`                            | Vector search over documents    | Knowledge (default) |
    | `query_graph`                                | Execute Cypher queries on Neo4j | Knowledge           |
    | `read_file`, `list_directory`, `grep_search` | Filesystem access               | Maintainer (opt-in) |
*   **Agent Modes**: Two security levels controlled via `agent_role` parameter:
    *   **Knowledge Agent** (default): Vector + Graph tools only. Safe for production.
    *   **Maintainer Agent**: Adds filesystem tools. Requires explicit opt-in.
*   **Resilient Content Fallback**: If Milvus returns empty content, the system automatically fetches from PostgreSQL, with full observability (OTel event + log metric).
*   **Implementation**: `src/core/generation/application/agent/`, `src/core/tools/`.

## API Reference

Full OpenAPI specification at `/docs`. Key endpoints:

### Core Endpoints

| Method     | Endpoint                    | Description                   |
| ---------- | --------------------------- | ----------------------------- |
| `POST`     | `/v1/query`                 | Submit a RAG query            |
| `GET/POST` | `/v1/query/stream`          | Stream query response via SSE |
| `POST`     | `/v1/documents`             | Upload a document             |
| `GET`      | `/v1/documents/{id}`        | Get document details          |
| `GET`      | `/v1/documents/{id}/status` | Check processing status       |

### Admin Endpoints

| Method | Endpoint                                   | Description                 |
| ------ | ------------------------------------------ | --------------------------- |
| `GET`  | `/v1/admin/jobs`                           | List background jobs        |
| `POST` | `/v1/admin/jobs/{id}/cancel`               | Cancel a job                |
| `POST` | `/v1/admin/maintenance/communities/detect` | Trigger community detection |
| `POST` | `/v1/admin/ragas/benchmark/run`            | Run evaluation              |

### Connector Endpoints

| Method | Endpoint                        | Description                        |
| ------ | ------------------------------- | ---------------------------------- |
| `GET`  | `/v1/connectors`                | List available connector types     |
| `GET`  | `/v1/connectors/{type}/status`  | Get connector status               |
| `POST` | `/v1/connectors/{type}/connect` | Authenticate with credentials      |
| `POST` | `/v1/connectors/{type}/sync`    | Trigger sync (full or incremental) |
| `GET`  | `/v1/connectors/{type}/items`   | Browse content from connector      |
| `POST` | `/v1/connectors/{type}/ingest`  | Ingest selected items by ID        |

## Application Structure

### 1. Consumer Interface (`/amber/chat`)
- Clean, focused chat interface
- Real-time streaming responses
- Inline citations with sources
- Follow-up question suggestions

### 2. Admin Dashboard (`/admin`)

#### Data Management (`/admin/data`)
- **Documents**: Upload, manage, view details
- **Database Overview**: Graph statistics
- **Query Log**: Granular inspection of recent RAG queries for debugging
- **Vector Store**: Milvus collection inspection

#### Operations (`/admin/ops`)
- **Jobs**: Monitor and control background tasks
- **Queues**: Real-time queue inspection
- **Tuning**: Dynamic parameter adjustment
- **Ragas**: Evaluation and benchmarking

## Development

### Local Development (Without Docker)

1. **Start Infrastructure**
   ```bash
   docker compose up -d postgres neo4j milvus redis garage etcd
   ```

2. **Backend**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn src.api.main:app --reload
   ```

3. **Worker**
   ```bash
   source .venv/bin/activate
   celery -A src.workers.celery_app worker --loglevel=info
   ```

4. **Frontend**
   ```bash
   cd frontend
   npm install
   npm run dev  # Runs on http://localhost:5173
   ```

### Production Build

The frontend ships a `Dockerfile.prod` and a Compose override that serve the built assets through Nginx instead of the Vite dev server.

### Code Style
```bash
make format  # Format code
make lint    # Run linter
make typecheck  # Type checking
```

### Database Migrations
```bash
make migrate-new  # Create migration
make migrate      # Run migrations
```

## Testing

See [docs/TESTING.md](docs/TESTING.md) for the full guide to unit, integration, and E2E tests.
```bash
make test          # Run all tests
make test-unit     # Unit tests only
make test-int      # Integration tests
make coverage      # With coverage report
```

## Performance & Scaling

### Query Latency (p95)

Indicative figures from a single development deployment on a ~10k-chunk corpus with `gpt-4o-mini`, not a benchmark. Your numbers will move with corpus size, model, and hardware.

| Search Mode | Cold   | Warm   |
| ----------- | ------ | ------ |
| Basic       | 800ms  | 250ms  |
| Local       | 1200ms | 400ms  |
| Global      | 2500ms | 800ms  |
| Drift       | 5000ms | 1500ms |

### Scaling Strategies

- **Horizontal**: Add more workers (`docker compose up -d --scale worker=4`)
- **Vertical**: Increase worker resources
- **Caching**: Tune Redis cache TTLs
- **Database**: Configure Neo4j/Milvus for your dataset size

## Troubleshooting

### Common Issues

**Services won't start**
```bash
docker compose logs api
docker compose restart api
```

**Document processing stuck**
```bash
docker compose logs -f worker
# Check worker for errors, restart if needed
```

**Query returns no results**
- Check document processing status
- Verify vector collection exists
- Check embeddings API key

**High memory usage**
- Reduce worker concurrency
- Clear caches
- Adjust Redis maxmemory

## Implementation Details

The ingestion pipeline, the query pipeline, and the caching and failure handling around both are documented in [docs/INTERNALS.md](docs/INTERNALS.md), down to the Cypher schemas and the chunking algorithm.

## Contributing

Contributions are welcome.

1. Fork & clone the repository
2. Create a feature branch
3. Make changes with tests
4. Run `make test` and `make lint`
5. Submit a pull request

Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

## License

Amber is released under the **MIT License**. See [LICENSE](LICENSE) for details. Release history is in [docs/CHANGELOG.md](docs/CHANGELOG.md).

