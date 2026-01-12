# Amber: The Sovereign AI Knowledge Assistant

## A Comprehensive Business & Technical Overview

**Document Version:** 1.0  
**Date:** January 2026  
**Classification:** Partner & Stakeholder Reference

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Vision](#2-product-vision)
3. [Technology Deep-Dive](#3-technology-deep-dive)
4. [Financial Analysis](#4-financial-analysis)
5. [Partner Strategy](#5-partner-strategy)
6. [Regional Market Fit](#6-regional-market-fit)
7. [Integration Capabilities](#7-integration-capabilities)
8. [Deployment & Operations](#8-deployment--operations)
9. [Roadmap & Future Vision](#9-roadmap--future-vision)
10. [Appendix](#10-appendix)

---

## 1. Executive Summary

### The Challenge

Modern enterprises are drowning in data but starving for insight. Knowledge workers spend an estimated 20% of their time searching for information across email, documents, wikis, and chat systems. Traditional search returns lists of links, forcing users to manually synthesize answers from multiple sources.

Simultaneously, enterprises face an impossible choice:
- **Use Cloud AI** (OpenAI, Microsoft Copilot) and accept data sovereignty risks
- **Avoid AI entirely** and fall behind competitors

### The Amber Solution

**Amber** is a sovereign, on-premise AI Knowledge Assistant that transforms how organizations interact with their data. Unlike cloud-based alternatives, Amber:

- **Never sends data outside your network** — 100% air-gapped operation
- **Builds a Knowledge Graph** — understands relationships, not just keywords
- **Synthesizes answers** — delivers insights, not document lists
- **Cites sources** — every answer is grounded and verifiable

### Key Value Propositions

| Stakeholder    | Value Delivered                                               |
| -------------- | ------------------------------------------------------------- |
| **End Users**  | 10x faster information retrieval with AI-synthesized answers  |
| **IT Teams**   | Complete control over data, deployment, and security policies |
| **Compliance** | GDPR, LGPD, Law 152-FZ compliance out of the box              |
| **Finance**    | 68% cost reduction vs. cloud AI over 3 years                  |
| **Partners**   | New revenue streams via hardware, services, and hosting       |

---

## 2. Product Vision

### 2.1 What is Amber?

Amber is a **private brain for your organization** — a self-hosted AI system that:

1. **Ingests your data** — PDFs, Documents, Email, Chat, Wikis
2. **Builds understanding** — Creates a Knowledge Graph of entities and relationships
3. **Answers questions** — Delivers precise, cited answers in natural language
4. **Takes action** — Queries calendars, searches chat history, drafts responses

### 2.2 The GraphRAG Difference

Traditional search and even standard RAG (Retrieval-Augmented Generation) systems suffer from fundamental limitations:

| Capability              | Standard Search  | Standard RAG        | Amber GraphRAG        |
| ----------------------- | ---------------- | ------------------- | --------------------- |
| **Input Understanding** | Keyword matching | Semantic similarity | Semantic + Structural |
| **Result Type**         | Document links   | Text chunks         | Synthesized answers   |
| **Context Window**      | None             | Local chunk         | Global + Multi-hop    |
| **Source Attribution**  | Document-level   | Chunk-level         | Entity + Relationship |
| **Complex Questions**   | ❌ Fails          | ⚠️ Partial           | ✅ Full support        |

**Example: "What are all the projects that John Smith is involved in, and for each, who else is working on them?"**

- **Standard Search**: Returns documents mentioning "John Smith"
- **Standard RAG**: May find some projects from a single document
- **Amber GraphRAG**: Traverses the Knowledge Graph to find all PROJECTS linked to John Smith entity, then follows WORKS_ON relationships to find all collaborators

### 2.3 Core Capabilities

#### Knowledge Engine

| Feature                    | Description                                                |
| -------------------------- | ---------------------------------------------------------- |
| **Multi-Format Ingestion** | PDF, DOCX, HTML, Markdown with intelligent extraction      |
| **Semantic Chunking**      | Structure-aware splitting that respects document hierarchy |
| **Entity Extraction**      | LLM-powered extraction of 30+ entity types                 |
| **Relationship Mapping**   | Automatic detection of connections between concepts        |
| **Community Detection**    | Hierarchical clustering via Leiden algorithm               |
| **Incremental Updates**    | Real-time knowledge base evolution                         |

#### Retrieval Modes

| Mode           | Use Case                   | Mechanism                             |
| -------------- | -------------------------- | ------------------------------------- |
| **Basic**      | Simple factual queries     | Hybrid vector search (Dense + Sparse) |
| **Local**      | Entity-specific questions  | Graph traversal from seed entities    |
| **Global**     | Thematic/summary questions | Map-reduce over community summaries   |
| **Drift**      | Complex reasoning queries  | Multi-hop iterative exploration       |
| **Structured** | List/count queries         | Direct Cypher execution               |

#### Agentic Capabilities

Amber's agent orchestrator enables multi-step reasoning:

1. **ReAct Loop**: Reason → Act → Observe → Repeat
2. **Tool Usage**: 
   - `search_codebase` — Vector search over documents
   - `query_graph` — Execute Cypher queries on Neo4j
   - `search_chats` — Query Carbonio chat history
   - `get_calendar` — Retrieve calendar events
3. **Guardrails**: Maximum 10 steps to prevent infinite loops

---

## 3. Technology Deep-Dive

### 3.1 System Architecture

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
└─────────────────────────────────────────────────────────────────┘
                    ▼                    ▼
┌─────────────────────────────┐  ┌──────────────────────────────┐
│      COMPUTE LAYER          │  │      WORKER LAYER            │
│  • Retrieval Service        │  │  • Celery Workers            │
│  • Generation Service       │  │  • Background Tasks          │
│  • Agent Orchestrator       │  │  • State Management          │
└─────────────────────────────┘  └──────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │ PostgreSQL │  │   Neo4j    │  │   Milvus   │                │
│  │ (Metadata) │  │  (Graph)   │  │ (Vectors)  │                │
│  └────────────┘  └────────────┘  └────────────┘                │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │   Redis    │  │   MinIO    │  │    etcd    │                │
│  │  (Cache)   │  │ (Storage)  │  │(Milvus MD) │                │
│  └────────────┘  └────────────┘  └────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Technology Stack

| Layer          | Component    | Technology                  | Purpose                         |
| -------------- | ------------ | --------------------------- | ------------------------------- |
| **Frontend**   | UI Framework | React 19 + Vite             | Modern reactive UI              |
|                | Router       | TanStack Router             | Type-safe routing               |
|                | State        | Zustand + TanStack Query    | Global & server state           |
|                | Styling      | Tailwind CSS + shadcn/ui    | Utility-first styling           |
|                | Graph Viz    | React Force Graph 2D/3D     | Interactive graph visualization |
| **API**        | Framework    | FastAPI 0.109+              | High-performance async API      |
|                | Validation   | Pydantic v2                 | Data validation                 |
|                | Auth         | API Keys (SHA-256)          | Secure authentication           |
| **Databases**  | Metadata     | PostgreSQL 16               | ACID-compliant relational data  |
|                | Graph        | Neo4j 5 Community           | Property graph with Cypher      |
|                | Vector       | Milvus 2.5+                 | Hybrid search (Dense + Sparse)  |
|                | Cache        | Redis 7                     | In-memory cache & broker        |
|                | Storage      | MinIO                       | S3-compatible object storage    |
| **Processing** | Task Queue   | Celery 5.3+                 | Distributed async processing    |
|                | Migrations   | Alembic                     | Database versioning             |
| **AI**         | LLM          | OpenAI, Anthropic, or Local | Text generation                 |
|                | Embeddings   | Text-embedding-3-small      | 1536-dimensional vectors        |
|                | Reranking    | FlashRank                   | Fast semantic reranking         |
|                | Clustering   | igraph + leidenalg          | Community detection             |

### 3.3 Data Processing Pipeline

The ingestion pipeline transforms raw documents through 8 stages:

1. **Storage** — Raw files stored in MinIO with content-addressed hashing
2. **Extraction** — Multi-parser fallback (PyMuPDF → Marker-PDF → Unstructured)
3. **Chunking** — 4-level hierarchical splitting (Headers → Code → Paragraphs → Sentences)
4. **Embedding** — Token-aware batching with exponential backoff retries
5. **Graph Extraction** — Two-pass extraction with "gleaning" for 15-25% recall improvement
6. **Vector Storage** — IVF_FLAT indexing in Milvus with <50ms query latency
7. **Graph Storage** — MERGE operations in Neo4j for idempotent writes
8. **Community Detection** — Hierarchical Leiden clustering with LLM summarization

### 3.4 Hybrid Search Architecture

Amber implements **Reciprocal Rank Fusion (RRF)** to combine multiple retrieval strategies:

```
Query → ┬─→ Dense Vector Search (Semantic) ─┬─→ RRF Fusion → Reranker → Results
        ├─→ Sparse Vector Search (SPLADE)  ─┤
        └─→ Graph Traversal (Multi-hop)    ─┘
```

**RRF Formula**: `score = Σ(weight / (k + rank))`

This ensures documents appearing in multiple result lists are ranked significantly higher.

### 3.5 Performance Characteristics

| Metric                 | Basic Mode | Local Mode | Global Mode | Drift Mode |
| ---------------------- | ---------- | ---------- | ----------- | ---------- |
| **P95 Latency (Cold)** | 800ms      | 1200ms     | 2500ms      | 5000ms     |
| **P95 Latency (Warm)** | 250ms      | 400ms      | 800ms       | 1500ms     |
| **Cache Hit Rate**     | ~60%       | ~50%       | ~40%        | ~30%       |
| **Token Usage**        | Low        | Medium     | High        | Very High  |

---

## 4. Financial Analysis

### 4.1 Usage Analysis Methodology

To build accurate cost models, we analyzed **6,600+ real-world interactions** from production deployments:

| Metric                   | Value            |
| ------------------------ | ---------------- |
| **Average Query Tokens** | ~2,100 tokens    |
| **Primary Cost Driver**  | Generation (95%) |
| **Embedding Cost**       | Negligible (<5%) |
| **Peak Load Factor**     | 3x average       |

### 4.2 Cost Comparison: Cloud vs On-Premise (1,000 Users, 3 Years)

#### Cloud API Model (GPT-4o)

| Period    | Monthly Cost | Cumulative   |
| --------- | ------------ | ------------ |
| Year 1    | $2,210       | $26,520      |
| Year 2    | $2,430       | $55,680      |
| Year 3    | $2,650       | $87,480      |
| **Total** | —            | **~$80,000** |

**Characteristics:**
- ❌ Trend: **Increasing** (API pricing, usage growth)
- ❌ Asset Value: **$0** (you're renting, not owning)
- ❌ Security: **Data leaves your premises**
- ❌ Dependency: **Single vendor lock-in**

#### Amber On-Premise Model

| Component             | Cost        | Amortization |
| --------------------- | ----------- | ------------ |
| GPU Server (RTX 4090) | $8,000      | 3-year       |
| Software License      | $5,000/year | Annual       |
| Setup & Integration   | $4,000      | One-time     |
| **3-Year Total**      | —           | **~$25,000** |

| Period    | Monthly Cost (Amortized) | Cumulative   |
| --------- | ------------------------ | ------------ |
| Year 1    | $700                     | $8,400       |
| Year 2    | $700                     | $16,800      |
| Year 3    | $700                     | $25,200      |
| **Total** | —                        | **~$25,000** |

**Characteristics:**
- ✅ Trend: **Flat** (inflation hedge)
- ✅ Asset Value: **Hardware owned**
- ✅ Security: **100% air-gapped**
- ✅ Flexibility: **Multi-vendor LLM support**

### 4.3 The $55,000 Opportunity

| Scenario         | 3-Year Cost | Savings       |
| ---------------- | ----------- | ------------- |
| Cloud API        | $80,000     | —             |
| Amber On-Premise | $25,000     | $55,000 (68%) |

> **Critical Insight**: For partners, this $55,000 gap represents **revenue opportunity**, not just customer savings. Instead of paying OpenAI, customers pay the partner for hardware, software, and services.

### 4.4 Total Cost of Ownership Factors

| Factor             | Cloud                 | On-Premise        | Advantage  |
| ------------------ | --------------------- | ----------------- | ---------- |
| **CapEx**          | $0                    | $12,000-$15,000   | Cloud      |
| **OpEx (3yr)**     | $80,000               | $15,000           | On-Premise |
| **Hidden Costs**   | Egress fees, overages | Power, cooling    | Varies     |
| **Scalability**    | Instant               | Hardware purchase | Cloud      |
| **Predictability** | Variable              | Fixed             | On-Premise |
| **Data Control**   | None                  | Complete          | On-Premise |

---

## 5. Partner Strategy

### 5.1 Revenue Stream Framework

Amber enables partners to capture value across the entire AI value chain:

```
┌─────────────────────────────────────────────────────────────┐
│                    AMBER PARTNER VALUE CHAIN                 │
├─────────────┬─────────────┬─────────────┬──────────────────┤
│   HARDWARE  │  APPLIANCE  │  SERVICES   │  MANAGED HOSTING │
│   (CapEx)   │  (License)  │  (Project)  │  (Recurring)     │
├─────────────┼─────────────┼─────────────┼──────────────────┤
│ GPU Servers │ Amber +     │ AI Readiness│ Sovereign MSP    │
│ Storage     │ Carbonio    │ Data Hygiene│ Housing          │
│ Networking  │ Integration │ Custom Dev  │ SLA Support      │
└─────────────┴─────────────┴─────────────┴──────────────────┘
```

### 5.2 Revenue Stream Details

#### Stream 1: Hardware Sales

| Opportunity        | Description                              | Typical Margin |
| ------------------ | ---------------------------------------- | -------------- |
| **GPU Servers**    | NVIDIA RTX 4090 or A100 configurations   | 15-25%         |
| **Storage Arrays** | High-capacity NVMe storage for documents | 20-30%         |
| **Refresh Cycles** | Regular hardware upgrades (3-year cycle) | 15-25%         |

**Example Configuration (1,000 Users):**
- 2x RTX 4090 GPU Server: $16,000
- 10TB NVMe Storage: $3,000
- Networking & UPS: $1,000
- **Partner Margin (20%)**: $4,000

#### Stream 2: Appliance/License Sales

| Offering             | Description                           | Price Point     |
| -------------------- | ------------------------------------- | --------------- |
| **Amber Core**       | Base platform license                 | $5,000/year     |
| **Amber Enterprise** | Multi-tenant, SSO, advanced analytics | $15,000/year    |
| **Carbonio Bundle**  | Amber + Carbonio CE                   | Bundled pricing |

#### Stream 3: Professional Services

| Service                          | Description                                      | Rate            |
| -------------------------------- | ------------------------------------------------ | --------------- |
| **AI Readiness Assessment**      | Evaluate data quality, infrastructure, use cases | $2,000-$5,000   |
| **Data Hygiene Audit**           | Clean, deduplicate, structure existing data      | $5,000-$15,000  |
| **Custom Connector Development** | Build integrations with proprietary systems      | $10,000-$30,000 |
| **Training & Enablement**        | User training, admin training, documentation     | $3,000-$10,000  |

#### Stream 4: Managed Hosting (Sovereign MSP)

| Model         | Description                         | Revenue             |
| ------------- | ----------------------------------- | ------------------- |
| **Dedicated** | Single-tenant hosted Amber instance | $2,000-$5,000/month |
| **Shared**    | Multi-tenant hosting with isolation | $500-$1,500/month   |
| **Hybrid**    | On-premise LLM, cloud management    | Custom pricing      |

### 5.3 Partner Value Proposition

**Why Partners Love Amber:**

| Benefit               | Description                                                  |
| --------------------- | ------------------------------------------------------------ |
| **Differentiation**   | "We offer true Private AI" — unique market position          |
| **Stickiness**        | Once knowledge is graphed, switching costs are enormous      |
| **Defensibility**     | Protects against Microsoft 365 Copilot encroachment          |
| **Control**           | Partner owns the customer relationship, not OpenAI/Microsoft |
| **Recurring Revenue** | Hardware refresh + license renewal + support contracts       |

### 5.4 Partner Enablement Program

| Level          | Requirements                         | Benefits                          |
| -------------- | ------------------------------------ | --------------------------------- |
| **Authorized** | Basic training, 1 deployment         | Deal registration, co-marketing   |
| **Certified**  | Advanced training, 3 deployments     | Enhanced margins, partner portal  |
| **Premier**    | Dedicated resources, 10+ deployments | Custom development, roadmap input |

---

## 6. Regional Market Fit

### 6.1 The Global Sovereignty Driver

Enterprises worldwide increasingly recognize the risks of cloud-hosted AI:

| Risk Category    | Description                                      | Impact              |
| ---------------- | ------------------------------------------------ | ------------------- |
| **Surveillance** | US Patriot Act enables forced data disclosure    | Legal liability     |
| **Sanctions**    | Service termination without notice (Kill Switch) | Business continuity |
| **Currency**     | USD-denominated OpEx creates budget volatility   | Financial planning  |
| **Compliance**   | Local regulations require data residency         | Legal compliance    |

**Amber solves ALL FOUR simultaneously** through 100% on-premise deployment.

### 6.2 Regional Analysis

#### Russia & CIS

| Requirement        | Amber Solution                       |
| ------------------ | ------------------------------------ |
| **Law 152-FZ**     | Complete data residency compliance   |
| **Sanction-Proof** | No US dependencies after deployment  |
| **Payment**        | No ongoing USD transactions required |
| **Technology**     | Works with Russian/Chinese hardware  |

**Deployment Model**: 100% Offline Amber (Air-gapped)

#### Brazil & LATAM

| Requirement       | Amber Solution                        |
| ----------------- | ------------------------------------- |
| **LGPD**          | Data never leaves Brazilian territory |
| **Currency**      | BRL-denominated partner contracts     |
| **Fines**         | Avoid €50M+ LGPD violation penalties  |
| **Local Support** | Regional partner ecosystem            |

**Deployment Model**: Partner-Hosted Sovereign Cloud

#### Europe (GDPR)

| Requirement    | Amber Solution                      |
| -------------- | ----------------------------------- |
| **Article 44** | No cross-border data transfers      |
| **Article 17** | Complete data deletion capability   |
| **DPO**        | Simplified compliance documentation |
| **Schrems II** | No US Cloud Act exposure            |

**Deployment Model**: On-Premise or EU-Hosted Partner Cloud

#### Middle East & Africa

| Requirement             | Amber Solution                    |
| ----------------------- | --------------------------------- |
| **Data Localization**   | In-country deployment             |
| **Technology Transfer** | Local partner capability building |
| **Risk Mitigation**     | No single-vendor dependencies     |

**Deployment Model**: Partner-Hosted National Cloud

### 6.3 Compliance Certifications (Roadmap)

| Standard      | Status     | Target  |
| ------------- | ---------- | ------- |
| ISO 27001     | Planned    | Q2 2026 |
| SOC 2 Type II | Planned    | Q3 2026 |
| GDPR Tooling  | Available  | Current |
| LGPD Tooling  | Available  | Current |
| FedRAMP       | Evaluation | Q4 2026 |

---

## 7. Integration Capabilities

### 7.1 Connector Architecture

Amber's connector framework enables integration with enterprise data sources:

```
External Service ←→ Connector ←→ Amber Knowledge Graph
                              ↓
                        Agent Tools
```

All connectors implement:
- `authenticate()` — Secure credential handling
- `fetch_items()` — Incremental sync support
- `get_agent_tools()` — Real-time agent interactions

### 7.2 Available Connectors

#### Carbonio (Zextras Suite)

| Capability      | Description                            |
| --------------- | -------------------------------------- |
| **Mail**        | Full email ingestion with metadata     |
| **Calendar**    | Event retrieval for scheduling queries |
| **Chats**       | XMPP/WebSocket chat history            |
| **Agent Tools** | Real-time search and retrieval         |

**Agent Tools:**
- `search_mail` — Query emails by subject, sender, content
- `get_calendar` — Retrieve events for availability checking
- `search_chats` — Find conversations by person or topic
- `get_chat_history` — Retrieve specific conversation threads

#### Confluence

| Capability           | Description            |
| -------------------- | ---------------------- |
| **Page Ingestion**   | Full wiki page content |
| **Incremental Sync** | `updated_at` filtering |
| **Metadata**         | Space, author, labels  |

#### Zendesk

| Capability           | Description               |
| -------------------- | ------------------------- |
| **Help Center**      | Article content ingestion |
| **Incremental Sync** | `updated_after` filtering |
| **Metadata**         | Category, author, votes   |

### 7.3 Custom Connector Development

Partners can build custom connectors for proprietary systems:

```python
from src.core.connectors.base import BaseConnector

class CustomSystemConnector(BaseConnector):
    def get_connector_type(self) -> str:
        return "custom_system"
    
    async def authenticate(self, credentials: dict) -> bool:
        # Implement authentication
        pass
    
    async def fetch_items(self, since=None):
        # Yield ConnectorItem instances
        pass
```

**Typical Development Timeline**: 2-4 weeks  
**Partner Service Opportunity**: $10,000-$30,000/connector

---

## 8. Deployment & Operations

### 8.1 Deployment Models

| Model              | Description                | Best For                      |
| ------------------ | -------------------------- | ----------------------------- |
| **Docker Compose** | Single-server deployment   | Development, Small teams      |
| **Kubernetes**     | Orchestrated multi-node    | Medium enterprises            |
| **Air-Gapped**     | Fully offline, no internet | High-security environments    |
| **Partner Hosted** | Managed sovereign cloud    | Customers without IT capacity |

### 8.2 Hardware Requirements

#### Minimum (50-100 Users)
| Component   | Specification            |
| ----------- | ------------------------ |
| **CPU**     | 8 cores                  |
| **RAM**     | 32 GB                    |
| **Storage** | 500 GB SSD               |
| **GPU**     | Optional (CPU inference) |

#### Recommended (500-1,000 Users)
| Component   | Specification               |
| ----------- | --------------------------- |
| **CPU**     | 16 cores                    |
| **RAM**     | 64 GB                       |
| **Storage** | 2 TB NVMe                   |
| **GPU**     | NVIDIA RTX 4090 (24GB VRAM) |

#### Enterprise (1,000+ Users)
| Component   | Specification            |
| ----------- | ------------------------ |
| **CPU**     | 32+ cores                |
| **RAM**     | 128+ GB                  |
| **Storage** | 10+ TB NVMe (RAID)       |
| **GPU**     | NVIDIA A100 or multi-GPU |

### 8.3 Capacity Planning

**Storage Formulas:**
- Raw Text: 1 MB per 500 pages
- Vector Index: `Num_Chunks × 1536 × 4 bytes`
- Graph: `Num_Nodes × 300 bytes + Num_Edges × 100 bytes`

**Scaling Triggers:**
- Scale API: CPU > 70% or P95 Latency > 2s
- Scale Workers: Ingestion Queue > 100 items
- Scale Database: Memory > 80%

### 8.4 Operational Features

| Feature              | Description                              |
| -------------------- | ---------------------------------------- |
| **Health Checks**    | Liveness and readiness probes            |
| **Circuit Breakers** | Automatic degradation under load         |
| **Job Management**   | Cancel, retry, monitor background tasks  |
| **Cache Management** | Clear semantic and result caches         |
| **Evaluation**       | Ragas benchmarking for quality assurance |

---

## 9. Roadmap & Future Vision

### 9.1 Current Release (v2.0)

✅ Hybrid GraphRAG (Vector + Graph)  
✅ Multi-mode retrieval (Basic, Local, Global, Drift)  
✅ Agentic RAG with tool usage  
✅ Carbonio, Confluence, Zendesk connectors  
✅ Multi-tenant architecture  
✅ Production-grade observability  

### 9.2 Near-Term Roadmap (H1 2026)

| Feature                  | Description                    | Target  |
| ------------------------ | ------------------------------ | ------- |
| **Local LLM Support**    | Mistral, Llama 3 integration   | Q1 2026 |
| **Voice Interface**      | Speech-to-text queries         | Q1 2026 |
| **SharePoint Connector** | Microsoft 365 file integration | Q2 2026 |
| **Slack Connector**      | Slack channel ingestion        | Q2 2026 |
| **Enhanced Analytics**   | Usage dashboards, ROI tracking | Q2 2026 |

### 9.3 Long-Term Vision (2026-2027)

| Capability                | Description                                              |
| ------------------------- | -------------------------------------------------------- |
| **Autonomous Agents**     | Multi-agent workflows for complex tasks                  |
| **Knowledge Versioning**  | Time-travel queries ("What did we know in 2024?")        |
| **Cross-Tenant Insights** | Anonymized benchmarking (opt-in)                         |
| **Industry Templates**    | Pre-configured ontologies for Legal, Healthcare, Finance |
| **Edge Deployment**       | Lightweight Amber for branch offices                     |

### 9.4 Partner Feedback Integration

Partner input directly influences roadmap priorities:
- **Premier Partners**: Quarterly roadmap review sessions
- **All Partners**: Feature voting via partner portal
- **Custom Development**: Fast-track integration of strategic connectors

---

## 10. Appendix

### 10.1 Glossary

| Term                 | Definition                                                             |
| -------------------- | ---------------------------------------------------------------------- |
| **GraphRAG**         | Retrieval-Augmented Generation enhanced with Knowledge Graph reasoning |
| **Hybrid Search**    | Combining dense (semantic) and sparse (keyword) vector search          |
| **Leiden Algorithm** | Community detection algorithm for hierarchical clustering              |
| **RRF**              | Reciprocal Rank Fusion — technique for combining ranked lists          |
| **Gleaning**         | Iterative LLM extraction to maximize recall                            |
| **Drift Search**     | Multi-hop agentic exploration with follow-up questions                 |

### 10.2 API Reference Summary

| Endpoint                        | Method   | Purpose                 |
| ------------------------------- | -------- | ----------------------- |
| `/v1/query`                     | POST     | Submit RAG query        |
| `/v1/query/stream`              | GET/POST | Stream response via SSE |
| `/v1/documents`                 | POST     | Upload document         |
| `/v1/documents/{id}`            | GET      | Get document details    |
| `/v1/connectors/{type}/connect` | POST     | Authenticate connector  |
| `/v1/connectors/{type}/sync`    | POST     | Trigger sync            |
| `/v1/admin/jobs`                | GET      | List background jobs    |

### 10.3 Security Architecture

| Layer         | Protection                               |
| ------------- | ---------------------------------------- |
| **API**       | API Keys (SHA-256 hashed), Rate limiting |
| **Data**      | Tenant isolation, Encrypted credentials  |
| **Transport** | TLS 1.3, mTLS optional                   |
| **Storage**   | At-rest encryption (MinIO, PostgreSQL)   |
| **Network**   | Air-gap capable, no egress required      |

### 10.4 Support & Resources

| Resource              | Location                   |
| --------------------- | -------------------------- |
| **Documentation**     | `/docs/` directory         |
| **API Specification** | `/docs` endpoint (OpenAPI) |
| **Partner Portal**    | Contact Zextras            |
| **Technical Support** | Partner tier-based SLA     |

---

## Document Information

**Prepared By:** Amber Product Team  
**Contact:** partners@zextras.com  
**Version:** 1.0  
**Last Updated:** January 2026

---

*Amber: Preserving Context, Revealing Insight*
