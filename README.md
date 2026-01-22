# Amber 

<img width="1533" height="447" alt="amber_avatar" src="https://github.com/user-attachments/assets/102873b7-5bc6-4a91-b688-3ef565d7c0d6" />

> **Preserving Context, Revealing Insight**

Amber 2.0 is a production-ready Hybrid GraphRAG (Graph Retrieval-Augmented Generation) system that combines vector similarity search with knowledge graph reasoning. It delivers deeply contextual, sourced, and high-quality answers over large document collections, with a focus on observability, robustness, and scalability.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/react-19-blue.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688.svg)](https://fastapi.tiangolo.com)

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Application Structure](#application-structure)
- [Development](#development)
- [Testing](#testing)
- [Performance & Scaling](#performance--scaling)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Amber processes documents through a sophisticated pipeline that extracts entities, relationships, and communities. Unlike traditional RAG systems that rely solely on semantic similarity, Amber understands the **structure** of your data through a hybrid approach combining:

- **Vector Search** for semantic similarity (Milvus)
- **Graph Traversal** for entity relationships (Neo4j)
- **Community Detection** for hierarchical clustering (Leiden Algorithm)
- **Dynamic Retrieval** with multiple search modes

### Why Amber?

**Traditional RAG systems** retrieve chunks based purely on vector similarity, often missing crucial context and relationships between concepts.

**Amber's Hybrid GraphRAG** builds a knowledge graph from your documents, understands entity relationships, detects communities of related concepts, and retrieves information using multiple strategies:

- **Basic Mode**: Fast vector-only search for simple queries
- **Local Mode**: Entity-focused graph traversal for precise lookups
- **Global Mode**: Map-reduce over community summaries for broad questions
- **Drift Search**: Iterative reasoning with follow-up questions for complex queries
- **Structured Mode**: Direct Cypher execution for list/count queries

---

## Key Features

<img width="1533" height="447" alt="architecture" src="https://github.com/user-attachments/assets/e4c4967b-b927-46f8-a9cf-93b3413ac7ae" />

### Intelligent Multi-Mode Retrieval

#### Vector & Hybrid Search (Basic Mode)
- **Hybrid Retrieval**: Combines Dense (Semantic) and Sparse (SPLADE) vectors for superior precision
- **Dense**: Text-embedding-3-small embeddings (1536 dimensions)
- **Sparse (New)**: Learned keyword expansion using SPLADE (cocondenser-ensembledistil)
- **Native Fusion**: Uses Reciprocal Rank Fusion (RRFRanker) in Milvus
- Result caching with Redis for performance

#### Graph-Enhanced Retrieval
- **Local Search**: Entity-focused traversal for precise information
- **Global Search**: Hierarchical community summaries for comprehensive answers
- **Drift Search**: Agentic, iterative exploration with dynamic follow-up questions
- **Graph Traversal**: Multi-hop relationship exploration

#### Advanced Query Processing
- **Query Rewriting**: Improves ambiguous or poorly-formed queries
- **Query Decomposition**: Breaks complex questions into sub-queries
- **HyDE (Hypothetical Document Embeddings)**: Generates hypothetical answers to improve retrieval
- **Query Routing**: Automatically selects the best search strategy
- **Structured Query Detection**: Bypasses RAG for simple list/count queries

### Advanced Knowledge Graph

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

### Robust Document Processing Pipeline

#### Multi-Format Support
- **PDF**: PyMuPDF4LLM, Marker-PDF, and Unstructured fallback
- **Markdown**: Native parsing with structure preservation
- **Text**: Direct ingestion
- **External Sources**: Connectors for Carbonio (Mail/Calendar/Chat), Confluence, Zendesk

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

#### Multi-Provider LLM Support
- **OpenAI**: GPT-4o, GPT-4o-mini, GPT-3.5-turbo
- **Anthropic**: Claude 3.5 Sonnet, Claude 3 Opus/Haiku
- **Ollama**: Local LLM support (Llama 3, Mistral, DeepSeek, Phi-3, Qwen, etc.)
- **Tiered Providers**: Economy (extraction), Standard (RAG), Premium (evaluation)
- **Streaming**: Server-Sent Events for real-time token streaming
- **Cost Tracking**: Token usage and cost estimation per query

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

### Production-Grade Admin & Operations

#### Document Management (`/admin/data`)
- **Upload Wizard**: Batch upload with drag-and-drop
- **Live Status Tracking**: Real-time ingestion progress
- **Document Details**: View chunks, entities, relationships, communities
- **Database Overview**: Graph statistics and health metrics
- **Vector Store Inspection**: Collection stats and memory usage
- **PDF Viewer**: In-browser PDF viewing with page navigation
- **Conversation Export**: Export chat history as PDF or Markdown

#### External Connectors (`/admin/connectors`)
- **Carbonio**: Integrate with Zextras Mail, Calendar, and Chats (includes Agent tools)
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

#### Maintenance & Operations
- **Community Detection**: Trigger full or incremental updates
- **Graph Enrichment**: Entity resolution and relationship strengthening
- **Index Optimization**: Rebuild vector indices
- **Cache Management**: Clear semantic and result caches
- **System Health**: Comprehensive health checks across all services

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

#### Authentication & Authorization
- **API Key Management**: SHA-256 hashed keys stored in PostgreSQL
- **Tenant Isolation**: Complete data separation between tenants
- **Rate Limiting**: Per-tenant request and upload limits
- **Upload Size Limits**: Configurable max file sizes

#### Error Handling & Resilience
- **Circuit Breakers**: Prevent cascade failures
- **Graceful Degradation**: Fallback to simpler modes on errors
- **Retry Logic**: Automatic retries with exponential backoff
- **Structured Logging**: JSON logs with request IDs
- **Health Checks**: Liveness and readiness probes

#### Observability
- **Request Tracing**: Request IDs for end-to-end tracking
- **Timing Metrics**: Detailed latency breakdowns (retrieval, generation, etc.)
- **Cache Hit Rates**: Monitor cache effectiveness
- **Query Metrics**: Track input/output tokens, costs, latency breakdowns (retrieval vs generation), and success/error rates per query.
- **Event Stream**: Real-time processing events via WebSockets

---

## System Architecture

Amber follows a microservices architecture designed for scalability, resilience, and separation of concerns.

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
│  │    Redis     │  │    MinIO     │  │  etcd (Milvus│         │
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
|                | Object Storage   | MinIO                     | S3-compatible file storage                |
| **Processing** | Task Queue       | Celery 5.3+               | Distributed async task processing         |
|                | Broker           | Redis                     | Task queue backend                        |
|                | Migrations       | Alembic                   | Database schema versioning                |
| **External**   | LLM Providers    | OpenAI, Anthropic         | Text generation & embeddings              |
|                | Extraction       | Unstructured, PyMuPDF4LLM | Multi-format document parsing             |
|                | Reranking        | FlashRank                 | Fast semantic reranking                   |
|                | Graph Clustering | igraph + leidenalg        | Community detection                       |
|                | Evaluation       | Ragas                     | RAG metrics evaluation                    |
| **Infra**      | Orchestration    | Docker Compose            | Service orchestration                     |

---

## Technical 

<img width="1536" height="447" alt="api" src="https://github.com/user-attachments/assets/047813df-68d9-4532-ba48-f8b3e6ab44b4" />

### 1. Ingestion & Semantic Processing

Amber's ingestion pipeline moves beyond simple text splitting by employing **structure-aware semantic chunking**.

*   **Hierarchy-First Splitting**: The `SemanticChunker` (`src/core/chunking/semantic.py`) respects document anatomy. It protects code blocks first, then splits by:
    1.  **Markdown Headers** (`#`, `##`, ...) to preserve topological context.
    2.  **Paragraphs** (`\n\n`) to maintain flow.
    3.  **Sentences** (via regex) as a last resort for dense text.
*   **Domain-Adaptive Sizing**: Chunk sizes and overlaps are automatically optimized based on document type (defined in `src/core/intelligence/strategies.py`):
    *   **General** (Default): 600 tokens / 50 overlap
    *   **Technical** (Code/Manuals): 800 tokens / 50 overlap
    *   **Scientific/Legal**: 1000 tokens / 100 overlap
    *   **Conversational**: 500 tokens / 100 overlap
*   **Token-Aware Overlap**: Rather than character-based overlap, tokens from the *end* of the previous chunk are prepended to the next to ensure semantic continuity.
*   **Chunk Quality Filtering**: Implements a helper "Quality Coloring" system (`ChunkQualityScorer`) that grades every chunk (0-1) based on text density, fragmentation, and OCR artifacts.
    *   **Noise Reduction**: Low-quality chunks (< 0.3) that also yield zero graph entities are automatically discarded during extraction, preventing "garbage-in" from polluting the vector store.
*   **Resilient Embedding**: The `EmbeddingService` uses exponential backoff retries for rate limits and utilizes **token-aware batching** (max 8000 tokens/batch) to optimize API throughput.

### 2. Knowledge Graph Construction

We don't just dump text into Neo4j; we construct a meaningful graph using **Iterative Extraction** and **Community Detection**.

*   **Entity Definition**: Entities are defined via flexible Pydantic models, supporting over 30+ domain-specific types alongside standard named entities.
    *   **Core Types**: `PERSON`, `ORGANIZATION`, `LOCATION`, `EVENT`, `CONCEPT`, `DOCUMENT`, `DATE`, `MONEY`.
    *   **Infrastructure Types**: `COMPONENT`, `SERVICE`, `NODE`, `DOMAIN`, `RESOURCE`, `STORAGE_OBJECT`, `BACKUP_OBJECT`.
    *   **Operational Types**: `ACCOUNT`, `ROLE`, `POLICY`, `TASK`, `PROCEDURE`, `CLI_COMMAND`, `API_OBJECT`, `CERTIFICATE`, `SECURITY_FEATURE`.
    *   **Schema**: Every extracted entity includes a `name` (capitalized), `type`, `description` (self-contained summary).
    *   **Relationships**: `source`, `target`, `type` (e.g., `DEPENDS_ON`, `PROTECTS`, `RUNS_ON`), and `weight` (1-10 strength score).
*   **Generation Mechanism (Dynamic Ontology Injection)**:
    *   The 30+ types are **dynamically injected** into the LLM system prompt as a canonical ontology (`{entity_types_str}`).
    *   The LLM is strictly instructed to classify entities *only* into these allowed types.
    *   **Output Format**: The system uses a strict **Tuple-Delimited Format** (e.g., `("entity"<|>NAME<|>TYPE...)`) to prevent parsing errors common with standard JSON, ensuring high-fidelity extraction even from messy text.
*   **Gleaning (Iterative Extraction)**: Implemented in `GraphExtractor`, this technique prevents "extraction amnesia."
    1.  **Pass 1**: Zero-shot extraction of entities and relationships (Temperature 0.1).
    2.  **Pass 2 (Gleaning)**: The LLM is fed the text *and* the entities found in Pass 1, and asked "What did you miss?". This significantly boosts recall for dense documents.
*   **Leiden Community Detection**: We use the hierarchical **Leiden algorithm** to cluster entities into communities.
    *   **Summarization**: Each community is summarized by an LLM to create a "Community Node," enabling **Global Search** (answering "What is the main theme?" by reading summaries rather than thousands of raw chunks).
*   **Quality Assurance (Hybrid Scoring)**: To prevent hallucinations and low-quality extractions, a strict scoring system is applied:
    *   **Intrinsic Confidence**: Entities with an LLM-generated `importance_score < 0.5` are automatically discarded.
    *   **Extrinsic Validation**: A `QualityScorer` module evaluates generated answers and critical extractions on 4 dimensions: **Context Relevance**, **Completeness**, **Factual Grounding**, and **Coherence**, using a mix of LLM evaluation and heuristic checks.


### 3. Advanced Retrieval Logic

Retrieval is handled by a sophisticated orchestration layer that combines deterministic and agentic strategies.

*   **Fusion (Hybrid Search)**: We employ **Reciprocal Rank Fusion (RRF)** to combine results from Milvus (Vector) and Neo4j (Keyword/Graph).
    *   **Milvus Hybrid**: Within Milvus itself, we combine **Dense Vectors** (Semantic) and **Sparse Vectors** (SPLADE/Keyword) to find the most relevant chunks.
    *   **Graph Fusion**: These results are then fused with graph traversals.
    *   Formula: `score = sum(weight / (k + rank))`
    *   This ensures that a document appearing in *both* top-lists is ranked significantly higher than one appearing in only one.
*   **Drift Search (Agentic)**: Defined in `DriftSearchService`, this is our most powerful retrieval mode:
    1.  **Primer**: Performs an initial standard retrieval (Top-5) to get a baseline context.
    2.  **Expansion Loop**: The LLM analyzes the Primer results and generates **Follow-Up Questions**. These sub-queries are executed to "drift" to related graph neighborhoods.
    3.  **Synthesis**: All accumulated context (Primer + Expansion) is deduplicated and fed to the LLM for a final, citation-backed answer.

### 4. Agentic RAG (ReAct Loop)

For complex queries requiring multi-step reasoning, Amber employs a full **Agentic RAG** architecture using a ReAct (Reason+Act) loop.

*   **Agent Orchestrator**: The `AgentOrchestrator` (`src/core/agent/orchestrator.py`) manages the loop:
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
*   **Documentation**: See [docs/agentic-retrieval.md](docs/agentic-retrieval.md) for full implementation details.

---

## Getting Started

<img width="1536" height="447" alt="pipeline" src="https://github.com/user-attachments/assets/f2792587-d68f-421f-83cb-a01ec260f91f" />

### Prerequisites

- **Docker & Docker Compose** (v2.0+) - Recommended for easiest setup
- **LLM API Key** - Required from either:
  - [OpenAI](https://platform.openai.com/) - GPT models
  - [Anthropic](https://console.anthropic.com/) - Claude models
- **System Resources** - Minimum:
  - 8 GB RAM (16 GB recommended)
  - 20 GB disk space
  - 2 CPU cores (4+ recommended)

### Quick Start (Docker - Recommended)

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/Amber_2.0.git
   cd Amber_2.0
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

   This starts 7 services:
   - `api` - FastAPI backend (port 8000)
   - `worker` - Celery workers
   - `postgres` - Metadata database (port 5432)
   - `neo4j` - Graph database (ports 7474, 7687)
   - `milvus` - Vector database (port 19530)
   - `redis` - Cache & broker (port 6379)
   - `minio` - Object storage (ports 9000, 9001)

4. **Run Database Migrations** (Critical!)
   ```bash
   make migrate
   # or: docker compose exec api alembic upgrade head
   ```

5. **Access the Application**
   - **Frontend (Dev)**: Build separately (see [Development](#development))
   - **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Neo4j Browser**: [http://localhost:7474](http://localhost:7474)
     - Username: `neo4j`
     - Password: (from `.env` NEO4J_PASSWORD)
   - **MinIO Console**: [http://localhost:9001](http://localhost:9001)
     - Username: `minioadmin` (default)
     - Password: `minioadmin` (default)

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

---

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
TENANT_ID=default
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
NEO4J_PASSWORD=graphrag123

# Milvus
MILVUS_HOST=milvus
MILVUS_PORT=19530

# Redis
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
```

#### LLM Providers
```ini
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-4o-mini

DEFAULT_EMBEDDING_PROVIDER=openai
DEFAULT_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

# Ollama (optional - for local LLMs)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
```

#### Rate Limiting
```ini
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_REQUESTS_PER_HOUR=1000
RATE_LIMIT_QUERIES_PER_MINUTE=20
RATE_LIMIT_UPLOADS_PER_HOUR=50
```

---

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

---

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

---

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

---

## Development

### Local Development (Without Docker)

1. **Start Infrastructure**
   ```bash
   docker compose up -d postgres neo4j milvus redis minio etcd
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

---

## Testing

See [TESTING.md](TESTING.md) for a comprehensive guide on running unit, integration, and E2E tests.
```bash
make test          # Run all tests
make test-unit     # Unit tests only
make test-int      # Integration tests
make coverage      # With coverage report
```

---

## Performance & Scaling

### Query Latency (p95)

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

---

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

---

## Technical Deep-Dive

This section provides detailed technical documentation of Amber's core pipelines and algorithms.

### Document Ingestion Pipeline

The ingestion pipeline transforms raw documents into queryable knowledge representations through multiple stages:

```
Document Upload
    ↓
[1] Storage (MinIO)
    ↓
[2] Format Detection & Extraction
    ↓
[3] Semantic Chunking
    ↓
[4] Embedding Generation
    ↓
[5] Graph Extraction (Entities & Relationships)
    ↓
[6] Vector Storage (Milvus)
    ↓
[7] Graph Storage (Neo4j)
    ↓
[8] Community Detection (Leiden)
    ↓
Document Ready
```

#### 1. Storage Layer

**Implementation**: [src/core/storage/storage_client.py](src/core/storage/storage_client.py:1)

- Raw documents stored in **MinIO** (S3-compatible object storage)
- Content-addressed storage using SHA-256 hashing
- Automatic deduplication at upload time
- Tenant-isolated buckets: `{tenant_id}/{document_id}/filename`

#### 2. Format Detection & Extraction

**Implementation**: [src/core/extraction/api/](src/core/extraction/api/)

Multi-parser fallback strategy:

```python
# Priority order:
1. PyMuPDF4LLM (PDF) - Fast, preserves structure
2. Marker-PDF (PDF) - Slower, better for complex layouts
3. Unstructured (PDF, DOCX, HTML) - Universal fallback
4. Native parsers (Markdown, TXT)
```

**PDF Extraction Pipeline**:
```python
async def extract_pdf(file_content: bytes) -> str:
    # Try fast parser first
    try:
        return pymupdf4llm.to_markdown(file_content)
    except Exception:
        # Fallback to robust parser
        return marker_pdf.convert(file_content)
```

**Output**: Markdown-formatted text with preserved structure (headers, lists, tables)

#### 3. Semantic Chunking

**Implementation**: [src/core/chunking/semantic.py](src/core/chunking/semantic.py:35)

**Hierarchical Splitting Strategy**:

Amber uses a **4-level hierarchical splitter** that respects document semantics:

```
Level 1: Headers (# ## ###)
    ↓
Level 2: Code Blocks (```)
    ↓
Level 3: Paragraphs (\n\n)
    ↓
Level 4: Sentences (.!?)
```

**Algorithm**:

1. **Code Block Protection**: Extract and replace code blocks with placeholders
2. **Header Splitting**: Divide by markdown headers to preserve logical sections
3. **Size-Aware Chunking**: For each section:
   - If fits in `chunk_size` → keep as-is
   - Else split by paragraphs
   - If paragraph too large → split by sentences
4. **Overlap Application**: Prepend last N tokens from previous chunk
5. **Token Counting**: Use tiktoken (`cl100k_base`) for accurate counts

**Configuration**:
```python
ChunkingStrategy(
    chunk_size=512,      # Target tokens per chunk
    chunk_overlap=50,    # Overlap tokens for context
)
```

**Example**:
```
Input (1000 tokens):
  # Introduction
  Paragraph 1 (300 tokens)
  Paragraph 2 (400 tokens)
  ## Methods
  Paragraph 3 (300 tokens)

Output:
  Chunk 0: "# Introduction\nParagraph 1\n" (300 tokens)
  Chunk 1: "[50 token overlap]Paragraph 2\n" (450 tokens)
  Chunk 2: "[50 token overlap]## Methods\nParagraph 3" (350 tokens)
```

**Metadata Enrichment**:
- `document_title`: For context
- `start_char`, `end_char`: Source location
- `index`: Chunk position in document
- `token_count`: Actual token count

#### 4. Embedding Generation

**Implementation**: [src/core/services/embeddings.py](src/core/services/embeddings.py:46)

**Production-Grade Embedding Pipeline**:

**Token-Aware Batching**:
```python
# Automatic batching by token count
MAX_TOKENS_PER_BATCH = 8000  # OpenAI limit
MAX_ITEMS_PER_BATCH = 2048   # API limit

batches = batch_texts_for_embedding(
    texts=chunks,
    model="text-embedding-3-small",
    max_tokens=8000,
    max_items=2048
)
```

**Retry Logic with Exponential Backoff**:
```python
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    retry=retry_if_exception_type((RateLimitError, ProviderUnavailableError))
)
async def _embed_batch_with_retry(texts, model):
    return await provider.embed(texts, model)
```

**Features**:
- **Parallel batching**: Process multiple batches concurrently
- **Cost tracking**: Track tokens and estimated costs per batch
- **Failover**: Automatic fallback to alternative providers
- **Statistics**: Detailed metrics (latency, tokens, failures)

**Semantic Caching**:

**Implementation**: [src/core/cache/semantic_cache.py](src/core/cache/semantic_cache.py:37)

```python
# Cache embeddings to avoid re-computation
key = SHA256(query.lower().strip())
cached_embedding = await cache.get(key)

if cached_embedding:
    return cached_embedding  # ~60% cache hit rate
else:
    embedding = await embed(query)
    await cache.set(key, embedding, ttl=86400)  # 24 hours
    return embedding
```

**Cache Performance**:
- Hit rate: ~60% in production workloads
- TTL: 24 hours (configurable)
- Storage: Redis with JSON serialization
- Speedup: 50ms vs 200ms (4x faster)

#### 5. Graph Extraction

**Implementation**: [src/core/extraction/graph_extractor.py](src/core/extraction/graph_extractor.py:16)

**Two-Pass Extraction with Gleaning**:

**Pass 1: Initial Extraction**
```python
# LLM prompt for structured extraction
system_prompt = """
Extract entities and relationships from the text.
Output JSON:
{
  "entities": [{"name": "...", "type": "...", "description": "..."}],
  "relationships": [{"source": "...", "target": "...", "type": "..."}]
}
"""

result = await llm.generate(text, system_prompt, temperature=0.0)
entities, relationships = parse_json(result)
```

**Pass 2: Gleaning (Iterative Refinement)**

Maximizes recall by asking the LLM to find missed entities:

```python
for iteration in range(max_gleaning_steps):  # default: 1
    existing_entities = [e.name for e in entities]

    prompt = f"""
    Text: {text}
    Existing Entities: {existing_entities}

    Find any entities you missed in the first pass.
    """

    new_entities = await llm.generate(prompt, temperature=0.2)

    if not new_entities:
        break  # No more entities found

    entities.extend(new_entities)
```

**Gleaning Impact**:
- Recall improvement: +15-25% more entities
- Cost: 2x LLM calls per chunk
- Trade-off: Configurable via `use_gleaning` flag

**Entity Schema**:
```python
{
    "id": "ent_abc123",
    "name": "GraphRAG",
    "type": "Technology",
    "description": "Hybrid retrieval system combining graphs and vectors",
    "tenant_id": "default",
    "source_chunks": ["chunk_1", "chunk_2"]
}
```

**Relationship Schema**:
```python
{
    "source": "ent_abc123",  # Entity ID
    "target": "ent_def456",
    "type": "ENABLES",
    "weight": 1.0,
    "description": "GraphRAG enables contextual retrieval"
}
```

#### 6. Vector Storage (Milvus)

**Implementation**: [src/core/vector_store/milvus.py](src/core/vector_store/milvus.py:1)

**Collection Schema**:
```python
# Chunk embeddings collection
Collection: "amber_{tenant_id}"
Fields:
  - chunk_id: VARCHAR (primary key)
  - document_id: VARCHAR
  - embedding: FLOAT_VECTOR(1536)  # text-embedding-3-small
  - content: TEXT
  - metadata: JSON

Index: IVF_FLAT
  - nlist: 1024
  - metric_type: IP (Inner Product ≈ Cosine for normalized vectors)
```

**Search Parameters**:
```python
search_params = {
    "metric_type": "IP",
    "params": {"nprobe": 16}  # Search 16 clusters
}

results = collection.search(
    data=[query_embedding],
    anns_field="embedding",
    param=search_params,
    limit=top_k,
    output_fields=["chunk_id", "content", "metadata"]
)
```

**Performance**:
- Query latency: <50ms for 100K vectors
- Indexing: ~5K vectors/second
- Memory: ~4GB per 1M vectors (1536 dims)

#### 7. Graph Storage (Neo4j)

**Implementation**: [src/core/graph/neo4j_client.py](src/core/graph/neo4j_client.py:1)

**Graph Schema**:

```cypher
// Nodes
(:Document {id, title, tenant_id, status})
(:Chunk {id, document_id, content, index})
(:Entity {id, name, type, description, tenant_id})
(:Community {id, level, title, tenant_id})

// Relationships
(:Chunk)-[:PART_OF]->(:Document)
(:Chunk)-[:MENTIONS]->(:Entity)
(:Entity)-[:RELATED_TO {type, weight}]->(:Entity)
(:Entity)-[:BELONGS_TO]->(:Community)
(:Community)-[:PARENT_OF]->(:Community)
```

**Indexes**:
```cypher
CREATE INDEX entity_tenant_idx FOR (e:Entity) ON (e.tenant_id);
CREATE INDEX entity_name_idx FOR (e:Entity) ON (e.name);
CREATE INDEX community_tenant_idx FOR (c:Community) ON (c.tenant_id, c.level);
```

**Write Pattern**:
```python
# Batched writes for performance
async def write_entities(entities: List[Entity]):
    query = """
    UNWIND $entities AS entity
    MERGE (e:Entity {id: entity.id})
    SET e.name = entity.name,
        e.type = entity.type,
        e.tenant_id = $tenant_id
    """
    await neo4j.execute_write(query, {"entities": entities})
```

#### 8. Community Detection (Leiden Algorithm)

**Implementation**: [src/core/graph/communities/leiden.py](src/core/graph/communities/leiden.py:12)

**Hierarchical Leiden Clustering**:

Amber uses the **Leiden algorithm** (Traag et al., 2019) for hierarchical community detection. Leiden improves upon Louvain by guaranteeing well-connected communities.

**Algorithm Steps**:

**Level 0: Entity Clustering**

1. **Fetch Entity Graph**:
```cypher
MATCH (s:Entity)-[r]->(t:Entity)
WHERE s.tenant_id = $tenant_id
RETURN s.id, t.id, type(r), r.weight
```

2. **Build igraph**:
```python
# Convert Neo4j graph to igraph
nodes = list(entity_ids)
edges = [(src, tgt, weight) for src, tgt, weight in relationships]

g = igraph.Graph(len(nodes))
g.add_edges(edges)
g.es['weight'] = weights
```

3. **Run Leiden**:
```python
partition = leidenalg.find_partition(
    g,
    leidenalg.RBConfigurationVertexPartition,
    weights=weights,
    resolution_parameter=1.0  # Higher = smaller communities
)
```

4. **Create Communities**:
```python
for comm_idx, members in enumerate(partition):
    community = Community(
        id=generate_community_id(level=0),
        level=0,
        members=[entity_ids[i] for i in members]
    )
```

**Level 1+: Hierarchical Aggregation**

5. **Aggregate Graph**:
```python
# Create super-graph where nodes are Level 0 communities
induced_graph = partition.cluster_graph()
```

6. **Recursive Leiden**:
```python
for level in range(1, max_levels):
    # Run Leiden on induced graph
    partition = leidenalg.find_partition(induced_graph, ...)

    # Create higher-level communities
    for super_comm in partition:
        community = Community(
            level=level,
            child_communities=[comm_ids from level-1]
        )

    # Check convergence
    if no_new_structure:
        break
```

**Persistence**:
```cypher
// Store communities and relationships
MERGE (c:Community {id: $id})
SET c.level = $level, c.title = $title

// Link entities (Level 0)
FOREACH (entity_id IN $members |
    MERGE (e:Entity {id: entity_id})
    MERGE (e)-[:BELONGS_TO]->(c)
)

// Link child communities (Level 1+)
FOREACH (child_id IN $children |
    MERGE (child:Community {id: child_id})
    MERGE (c)-[:PARENT_OF]->(child)
)
```

**Community Summarization**:

After detection, each community is summarized using an LLM:

```python
# Gather community content
entities = get_community_entities(community_id)
chunks = get_related_chunks(entities)

prompt = f"""
Summarize the following content as a coherent theme:

Entities: {entity_names}
Context: {chunk_contents}

Provide:
1. A title (5-10 words)
2. A summary (2-3 sentences)
3. Key themes (3-5 keywords)
"""

summary = await llm.generate(prompt)
community.summary = summary.text
community.embedding = await embed(summary.text)
```

**Why Leiden?**
- **Quality**: Guarantees well-connected communities (vs Louvain)
- **Speed**: O(n log n) on sparse graphs
- **Hierarchical**: Natural multi-level structure
- **Proven**: Standard in network science

---

### Query Processing Pipeline

The query pipeline transforms user questions into contextual answers through multiple stages:

```
User Query
    ↓
[1] Query Rewriting
    ↓
[2] Query Parsing & Filtering
    ↓
[3] Query Routing (Mode Selection)
    ↓
[4] Query Enhancement (HyDE/Decomposition)
    ↓
[5] Multi-Modal Search
    ↓
[6] Result Fusion & Reranking
    ↓
[7] Answer Generation
    ↓
Response
```

#### 1. Query Rewriting

**Implementation**: [src/core/query/rewriter.py](src/core/query/rewriter.py:19)

**Purpose**: Convert context-dependent queries into standalone versions.

**Example**:
```python
# Conversation history
History:
  User: "What is GraphRAG?"
  AI: "GraphRAG is a hybrid retrieval system..."
  User: "How does it work?"  # ← Ambiguous!

# Rewriting
Original: "How does it work?"
Rewritten: "How does GraphRAG work?"
```

**Implementation**:
```python
prompt = f"""
Conversation History:
{format_history(last_5_turns)}

Current Query: {query}

Rewrite the query to be standalone and clear.
Output only the rewritten query.
"""

rewritten = await llm.generate(prompt, temperature=0.0)
```

**Features**:
- Uses conversation history (last 5 turns)
- Timeout guard (2 seconds, fallback to original)
- Uses economy-tier LLM for cost efficiency

#### 2. Query Parsing & Filtering

**Implementation**: [src/core/query/parser.py](src/core/query/parser.py:1)

**Extract Structured Filters**:

```python
# Parse filters from natural language
query = "Show me documents about AI from 2024 tagged research"

parsed = QueryParser.parse(query)
# Output:
{
    "cleaned_query": "documents about AI",
    "filters": {
        "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
        "tags": ["research"]
    },
    "document_ids": []
}
```

**Supported Filters**:
- Date ranges: "from Jan 2024", "between 2023-2024"
- Tags: "tagged X", "#X"
- Document IDs: "in doc_123", "document doc_abc"

#### 3. Query Routing

**Implementation**: [src/core/query/router.py](src/core/query/router.py:1)

**Automatic Search Mode Selection**:

```python
async def route(query: str) -> SearchMode:
    """
    Classify query and select optimal search mode.
    """
    prompt = f"""
    Classify this query:

    Query: {query}

    Categories:
    - LIST: Enumeration queries ("list all", "what are")
    - ENTITY: Specific entity lookup ("who is", "when did")
    - THEME: Broad conceptual questions ("how does", "explain")
    - COMPARISON: Comparing concepts ("difference between")
    - SIMPLE: Direct factual question

    Return: BASIC | LOCAL | GLOBAL | DRIFT | STRUCTURED
    """

    mode = await llm.generate(prompt)
    return SearchMode(mode.strip())
```

**Mode Selection Logic**:
- **STRUCTURED**: Direct Cypher for "list all X", "count Y"
- **LOCAL**: Entity-centric for "who", "when", "where"
- **GLOBAL**: Community summaries for "what themes", "overview"
- **DRIFT**: Iterative for "how does X relate to Y", multi-hop
- **BASIC**: Fallback vector search

#### 4. Query Enhancement

**HyDE (Hypothetical Document Embeddings)**

**Implementation**: [src/core/query/hyde.py](src/core/query/hyde.py:19)

**Technique**: Generate hypothetical answers, embed them instead of the query.

**Why?** Bridges semantic gap between short queries and long documents.

```python
query = "What is the capital of France?"

# Generate hypothesis
hypothesis = await llm.generate(f"""
Generate a passage that would answer: {query}

Write 2-3 sentences as if from a Wikipedia article.
""")
# Output: "Paris is the capital and largest city of France.
#          Located on the Seine River, Paris is known for..."

# Embed hypothesis instead of query
embedding = await embed(hypothesis)
results = vector_search(embedding)
```

**Consistency Check**:
```python
# Generate multiple hypotheses
hypotheses = [await generate_hypothesis(query) for _ in range(3)]
embeddings = [await embed(h) for h in hypotheses]

# Check semantic consistency
avg_similarity = cosine_similarity_matrix(embeddings).mean()
if avg_similarity < 0.7:
    logger.warning("Inconsistent hypotheses, fallback to direct query")
    use_direct_query()
```

**Query Decomposition**

**Implementation**: [src/core/query/decomposer.py](src/core/query/decomposer.py:1)

**Technique**: Break complex multi-part questions into sub-queries.

```python
query = "How does GraphRAG compare to traditional RAG and what are its advantages?"

sub_queries = await decompose(query)
# Output:
[
    "What is GraphRAG?",
    "What is traditional RAG?",
    "How does GraphRAG differ from traditional RAG?",
    "What are the advantages of GraphRAG?"
]

# Execute in parallel
results = await asyncio.gather(*[
    retrieve(sq) for sq in sub_queries
])

# Aggregate results
combined_context = fuse_results(results)
```

#### 5. Multi-Modal Search

Amber supports 5 search modes, each optimized for different query types.

**Basic Mode: Vector-Only Search**

```python
# Standard semantic similarity search
embedding = await embed(query)
results = milvus.search(
    data=[embedding],
    limit=10,
    metric="IP"  # Inner product (cosine for normalized)
)
```

**Local Mode: Entity-Focused Graph Traversal**

**Implementation**: [src/core/retrieval/search/graph.py](src/core/retrieval/search/graph.py:1)

```python
# 1. Find entities matching query
entity_embedding = await embed(query)
entities = entity_search(entity_embedding, limit=3)

# 2. Traverse graph from entities
for entity in entities:
    # Get 2-hop neighborhood
    cypher = """
    MATCH (e:Entity {id: $entity_id})
    MATCH (e)-[r1]-(neighbor)
    MATCH (neighbor)-[r2]-(extended)
    RETURN e, r1, neighbor, r2, extended
    """

    neighborhood = await neo4j.execute_read(cypher)

    # 3. Get chunks mentioning these entities
    chunks = get_chunks_mentioning(neighborhood.entities)

    candidates.extend(chunks)
```

**Global Mode: Community Summary Map-Reduce**

**Implementation**: [src/core/retrieval/global_search.py](src/core/retrieval/global_search.py:1)

```python
# 1. Search community summaries
summary_embedding = await embed(query)
communities = search_community_summaries(summary_embedding, limit=5)

# 2. For each community, get member entities and chunks
community_contexts = []
for community in communities:
    entities = get_community_entities(community.id)
    chunks = get_related_chunks(entities)
    community_contexts.append({
        "summary": community.summary,
        "chunks": chunks
    })

# 3. Map-Reduce generation
intermediate_answers = await asyncio.gather(*[
    llm.generate(f"Based on: {ctx['summary']}\n{ctx['chunks']}\n\nAnswer: {query}")
    for ctx in community_contexts
])

# 4. Final reduce step
final_answer = await llm.generate(f"""
Synthesize these partial answers into a comprehensive response:

{intermediate_answers}

Question: {query}
""")
```

**Drift Mode: Iterative Agentic Search**

**Implementation**: [src/core/retrieval/drift_search.py](src/core/retrieval/drift_search.py:10)

DRIFT = **D**ynamic **R**easoning and **I**nference with **F**lexible **T**raversal

**Three-Phase Process**:

```python
async def drift_search(query, max_iterations=3):
    all_context = []

    # Phase 1: Primer - Initial retrieval
    initial_results = await retrieve(query, top_k=5)
    all_context.extend(initial_results)

    # Phase 2: Expansion - Iterative follow-ups
    for iteration in range(max_iterations):
        # Generate follow-up questions
        prompt = f"""
        Query: {query}
        Current Context: {all_context}

        What 3 questions would help provide a more complete answer?
        If context is sufficient, respond 'DONE'.
        """

        follow_ups = await llm.generate(prompt)

        if "DONE" in follow_ups:
            break

        # Execute follow-up searches in parallel
        follow_up_results = await asyncio.gather(*[
            retrieve(fq, top_k=3) for fq in parse_questions(follow_ups)
        ])

        # Add only new, non-duplicate chunks
        for chunks in follow_up_results:
            for chunk in chunks:
                if chunk.id not in seen_ids:
                    all_context.append(chunk)
                    seen_ids.add(chunk.id)

    # Phase 3: Synthesis - Final generation
    answer = await llm.generate(f"""
    Question: {query}
    Context: {all_context}

    Provide a comprehensive, grounded answer with citations.
    """)

    return answer
```

**Example Flow**:
```
Query: "How does attention mechanism relate to transformers?"

Iteration 0 (Primer):
  Retrieved: ["Attention basics", "Transformer overview"]

Iteration 1:
  Follow-ups: ["What is self-attention?", "What is multi-head attention?"]
  Retrieved: ["Self-attention formula", "Multi-head details"]

Iteration 2:
  Follow-ups: ["How are they used in transformers?"]
  Retrieved: ["Transformer architecture", "Attention in encoder-decoder"]
  Context deemed sufficient → DONE

Synthesis:
  Generates comprehensive answer from 6 chunks
```

**Structured Mode: Direct Cypher Execution**

For simple enumeration/count queries, bypass RAG entirely:

```python
query = "List all documents about AI"

cypher = """
MATCH (d:Document)-[:HAS_TAG]->(t:Tag {name: "AI"})
RETURN d.title, d.created_at
ORDER BY d.created_at DESC
LIMIT 50
"""

results = await neo4j.execute_read(cypher)
return format_list(results)
```

#### 6. Result Fusion & Reranking

**Reciprocal Rank Fusion (RRF)**

**Implementation**: [src/core/retrieval/fusion.py](src/core/retrieval/fusion.py:1)

When combining results from multiple sources (vector + graph + entity), use RRF:

```python
def reciprocal_rank_fusion(
    results_lists: List[List[Candidate]],
    k: int = 60  # RRF constant
) -> List[Candidate]:
    """
    Fuse multiple ranked lists using RRF.

    RRF Score = Σ(1 / (k + rank_i))
    """
    scores = defaultdict(float)

    for results in results_lists:
        for rank, candidate in enumerate(results):
            scores[candidate.id] += 1.0 / (k + rank + 1)

    # Sort by RRF score
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [get_candidate(id) for id, score in fused]
```

**Example**:
```
Vector Search:     [A, B, C, D]
Graph Search:      [C, A, E, F]
Entity Search:     [E, A, B, G]

RRF Scores:
  A: 1/61 + 1/62 + 1/62 = 0.049
  B: 1/62 + 1/63 = 0.032
  C: 1/63 + 1/61 = 0.032
  E: 1/64 + 1/61 = 0.032
  ...

Fused: [A, B, C, E, D, F, G]
```

**Semantic Reranking**

**Implementation**: [src/core/providers/local.py](src/core/providers/local.py:1) (FlashRank)

After fusion, rerank top-k candidates using a cross-encoder:

```python
# Get top 50 from vector/graph fusion
candidates = fuse_results([vector_results, graph_results], top_k=50)

# Rerank using cross-encoder
reranker = FlashRankReranker()
reranked = await reranker.rerank(
    query=query,
    documents=[c.content for c in candidates],
    top_k=10
)
```

**Cross-Encoder vs Bi-Encoder**:
- **Bi-Encoder** (Vector Search): Encode query and docs separately, compare embeddings (fast, ~50ms)
- **Cross-Encoder** (Reranking): Encode query+doc together, predict relevance (accurate, ~200ms)

**Reranking improves precision by +15-20% but adds latency.**

#### 7. Answer Generation

**Implementation**: [src/core/services/generation.py](src/core/services/generation.py:1)

**Prompt Engineering**:

```python
system_prompt = """
You are an expert analyst. Answer the question using ONLY the provided context.

Rules:
1. Base your answer solely on the context
2. Cite sources using [1], [2] notation
3. If context insufficient, say "I don't have enough information"
4. Be concise but complete
"""

user_prompt = f"""
Question: {query}

Context:
{format_sources(chunks)}

Provide a detailed answer with citations.
"""

answer = await llm.generate(user_prompt, system=system_prompt)
```

**Citation Extraction**:
```python
# Parse [1], [2] citations from answer
citations = extract_citations(answer.text)

# Map to source chunks
sources = [
    {
        "chunk_id": chunks[i].id,
        "document": chunks[i].document,
        "text": chunks[i].content,
        "score": chunks[i].score
    }
    for i in citations
]
```

**Streaming Response**:
```python
async def stream_answer(query, chunks):
    prompt = format_prompt(query, chunks)

    async for token in llm.stream(prompt):
        yield {
            "type": "token",
            "content": token
        }

    yield {
        "type": "sources",
        "content": format_sources(chunks)
    }
```

---

### Performance Optimizations

#### Caching Strategy

**Three-Layer Cache**:

1. **Embedding Cache** (Redis, 24h TTL)
   - Key: SHA256(query.lower())
   - Saves ~200ms per cached query
   - Hit rate: ~60%

2. **Result Cache** (Redis, 30min TTL)
   - Key: SHA256(query + filters + options)
   - Saves ~1000ms per cached query
   - Hit rate: ~40%

3. **Community Summary Cache** (Redis, 1h TTL)
   - Pre-computed community summaries
   - Saves 5-10s on global search

#### Batch Processing

**Embedding Batching**:
```python
# Instead of: for chunk in chunks: embed(chunk)
# Use batching:
embeddings = await embed_batch(chunks, batch_size=100)
# 10x faster for large documents
```

**Graph Write Batching**:
```python
# Batch entity writes
async def write_entities(entities):
    for batch in chunk_list(entities, size=100):
        await neo4j.execute_write(batch_query, batch)
```

#### Parallel Execution

```python
# Execute searches in parallel
vector_task = vector_search(embedding)
entity_task = entity_search(embedding)
graph_task = graph_traverse(entities)

results = await asyncio.gather(
    vector_task,
    entity_task,
    graph_task,
    return_exceptions=True  # Don't fail if one fails
)
```

#### Circuit Breaker

**Implementation**: [src/core/system/circuit_breaker.py](src/core/system/circuit_breaker.py:1)

Prevents cascade failures:

```python
circuit_breaker = CircuitBreaker(
    failure_threshold=5,   # Open after 5 failures
    timeout=60,            # Stay open for 60s
    half_open_max=3        # Try 3 requests when half-open
)

if circuit_breaker.is_open():
    # Fallback to simpler search mode
    return basic_vector_search(query)
else:
    try:
        result = await complex_graph_search(query)
        circuit_breaker.record_success()
    except Exception:
        circuit_breaker.record_failure()
        raise
```

---

## Contributing

We welcome contributions!

1. Fork & clone the repository
2. Create a feature branch
3. Make changes with tests
4. Run `make test` and `make lint`
5. Submit a pull request

Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

---

## Roadmap

- [ ] Multi-modal support (images, audio)
- [ ] Real-time document updates
- [ ] 3D graph visualization
- [ ] Multi-tenant UI
- [ ] Conversation memory
- [ ] Export functionality
- [ ] Plugin system

---

## License

Amber 2.0 is released under the **MIT License**. See [LICENSE](LICENSE) for details.

---
