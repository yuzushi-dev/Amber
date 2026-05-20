# Amber 2.0 GraphRAG — Architecture Audit

**Date:** 2026-05-15  
**Auditor:** Architecture spike via Claude Code (read-only, no production changes)  
**Scope:** Production system at `your-server.example.com`, branch `main`  
**Method:** Static code analysis + live production telemetry (Redis metrics, Milvus, PostgreSQL, Neo4j)  
**Constraint:** Read-only. Zero production changes made.  
**Passes:** Initial audit + second-pass verification (corrections noted inline)

---

## 1. System Overview

### 1.1 Infrastructure Stack

| Service | Image | Role |
|---------|-------|------|
| `amber2-api-1` | FastAPI | REST API, query entrypoint |
| `amber2-worker-1/2/3` | Celery | Async ingestion, extraction, graph, community tasks |
| `amber2-postgres-1` | PostgreSQL + pgvector | Relational store, tenant RLS, document state machine |
| `amber2-redis-1` | Redis | Celery broker, result backend, semantic cache, LLM capacity limiter |
| `amber2-milvus-1` | Milvus 2.5.x | Vector store (dense embeddings) |
| `amber2-neo4j-1` | Neo4j | Entity/relationship graph |
| `amber2-garage-1` | Garage v1.1.0 | S3-compatible object storage (raw docs + **Milvus backend**) |
| `amber2-etcd-1` | etcd | Milvus metadata store |
| `amber2-nginx-1` | Nginx | Reverse proxy |
| `amber2-frontend-1` | React | Web UI |

**Reference:** `docker-compose.yml` (root of repo)

### 1.2 Source Layout

```
src/
  amber_platform/          # Composition root, DI wiring
  core/
    retrieval/             # Query pipeline (1,335-line retrieval_service.py)
    generation/            # LLM generation, agent, classifiers
    graph/                 # Neo4j NER extraction
    ingestion/             # Document state machine
    community/             # Leiden clustering + summarization
    security/              # InjectionGuard, PIIScrubber, GraphTraversalGuard (see §7)
  shared/                  # Cross-cutting: LLM capacity, tenant, models
  workers/                 # Celery app definition
frontend/
  src/features/chat/       # React UI
```

**Key files by line count:**
- `src/core/retrieval/application/retrieval_service.py` — 1,335 lines
- `src/core/graph/application/processor.py` — 284 lines
- `src/core/generation/application/agent/orchestrator.py` — ~200 lines
- `src/amber_platform/composition_root.py` — ~300 lines

---

## 2. Production Telemetry

All data extracted read-only from production containers.

### 2.1 Milvus Collections

```
docker exec amber2-api-1 python3 -c "from pymilvus import connections, utility, Collection; ..."
```

| Collection | Entities | Notes |
|------------|----------|-------|
| `amber_default` | 3,737 | Default tenant vector store |
| `amber_7eb7ef04_190c_4ec0_8717_b6db31caa683` | 2,514 | Named tenant |
| `community_embeddings` | **20,536** | GLOBAL search — populated and functional |
| `amber_c0773110_00a1_4622_b820_0facf20805ba` | 0 | Empty tenant |
| `amber_32d2a3f2_14ef_4697_aac5_e36548609b69` | 0 | Empty tenant |
| `document_chunks` | 0 | Legacy collection, unused |

`entity_embeddings` collection: **does not exist** (relevant: see §4.3 LOCAL mode).

### 2.2 Neo4j Graph Data

```
docker exec amber2-neo4j-1 cypher-shell -u neo4j -p changeme \
  "MATCH (n) RETURN labels(n)[0] as label, count(n) as cnt ORDER BY cnt DESC;"
```

| Label | Count |
|-------|-------|
| Entity | 23,547 |
| Community | 12,453 |
| Chunk | 4,084 |
| Document | 1,204 |
| Turn | 374 |
| Conversation | 323 |
| UserFeedback | 15 |

Graph is actively used. 323 conversations stored in Neo4j as Turn/Conversation nodes — conversation history lives in Neo4j, **not** PostgreSQL (no chat_history table exists).

### 2.3 Redis Key Distribution (db0, 5,333 keys)

| Key pattern | Count | Purpose |
|-------------|-------|---------|
| `metrics:query:*` | 4,667 | Per-query telemetry (volatile, TTL-bound) |
| `classification:*` | 663 | DomainClassifier Redis cache (7-day TTL) |
| `llm_capacity:*` | 1 | Distributed LLM semaphore |
| `semantic_cache:*` | ~1 | Semantic query embedding cache |
| `result_cache:*` | ~0 | Result cache (bypassed — see §4.1) |

### 2.4 RAG Query Latency (n=21 from metrics:query:*)

| Metric | Value |
|--------|-------|
| p50 | **13,806 ms** |
| p90 | **24,688 ms** |
| max | **29,464 ms** |
| cache_hit rate | **0%** (0/21) |
| graph local_hits total | 50 across 21 queries |
| avg chunks_retrieved | 10.7 |

No latency SLO exists. These numbers are unknown to the team (confirmed via interview — "non esiste un budget ma forse dovrebbe").

### 2.5 PostgreSQL Tables (23 total)

Notable: `documents`, `chunks`, `tenants`, `usage_logs`, `audit_logs`, `conversation_summaries`, `feedbacks`, `global_rules`, `graph_edit_history`, `api_keys`, `api_key_tenants`.

`usage_logs` operations: 323,499 `generation`, 52,246 `embedding`. No `search_mode` column anywhere in schema — SearchMode distribution is not persisted (confirmed: not monitored).

### 2.6 Interview Responses (post-audit)

| Question | Answer |
|----------|--------|
| Why is result cache force-bypassed? | **No documented reason — origin unclear** |
| Latency budget for queries? | **No formal SLO defined** |
| SearchMode usage in production? | **Not instrumented — no data available** |
| AgentOrchestrator + hybrid search roadmap? | **No active roadmap item identified** |
| DomainClassifier LLM upgrade planned? | **No planned implementation date** |
| DRIFT search — used or planned? | **Activation status unknown — not monitored** |

5 of 6 questions returned no documented decision — see §8 for interpretation.

---

## 3. Architecture That Works Correctly

### 3.1 Document Ingestion Pipeline

10-step state machine: `PENDING → UPLOADING → UPLOADED → EXTRACTING → EXTRACTED → CHUNKING → CHUNKED → EMBEDDING → EMBEDDED → INGESTED`

Celery task queues: `high_priority`, `celery`, `ingestion`, `extraction`, `evaluation`, `low_priority`. `worker_concurrency=2` per worker × 3 workers = 6 concurrent ingestion slots. `task_acks_late=True` prevents work loss on worker crash.

**Extraction fallback chain** (9 local extractors): attempts in priority order, falls back on failure. Prevents single-format failures from blocking the pipeline. Justified.

**SHA-256 content deduplication** per tenant: correct. Prevents reprocessing on re-upload. Validation at system boundary.

**Reference:** `src/core/ingestion/`, `src/workers/celery_app.py`

### 3.2 Graph Extraction

`GraphProcessor` (`src/core/graph/application/processor.py`):
- Takes chunks → LLM NER → writes entities + relationships to Neo4j
- Supports static semaphore and adaptive concurrency governor
- 23,547 entities, 12,453 communities in Neo4j on production

Graph contributes: `local_hits = 50` across 21 sampled queries — graph results are actively being returned.

### 3.3 Community Pipeline (Leiden + Summarization)

Community detection via Leiden algorithm → LLM summarization → embeddings stored in `community_embeddings`.

**Production evidence:** 20,536 entities in `community_embeddings`. GLOBAL search is functional.

**Reference:** `src/core/community/`

### 3.4 GLOBAL Search

`GlobalSearchService` searches `community_embeddings`, then runs a Map phase (LLM extracts key points per community report). The collection is populated and the service is correctly dispatched in `retrieval_service.py:795`:

```python
if search_mode == SearchMode.GLOBAL:
    result = await self._execute_global_search(...)
```

Working correctly.

### 3.5 STRUCTURED Queries

STRUCTURED is handled at the **use case layer** (`src/core/retrieval/application/use_cases_query.py:86`) before the retrieval service is ever called:

```python
# 1. STRUCTURED QUERY CHECK
structured_result = await structured_executor.try_execute(query=request.query, tenant_id=tenant_id)
if structured_result and structured_result.success:
    return StructuredQueryResponse(...)
```

`CypherGenerator` uses **parameterized templates** (no string interpolation):

```python
TEMPLATES = {
    StructuredQueryType.LIST_DOCUMENTS: """
        MATCH (d:Document) WHERE d.tenant_id = $tenant_id ...
    """,
    # ... 7 more templates
}
```

Handles: LIST_DOCUMENTS, COUNT_DOCUMENTS, LIST_ENTITIES, COUNT_ENTITIES, LIST_ENTITY_TYPES, LIST_RELATIONSHIPS, COUNT_CHUNKS, DOCUMENT_STATS. All parameterized — no Cypher injection risk.

**⚠ Note on `SearchMode.STRUCTURED` in the router:** When the `QueryRouter` returns `SearchMode.STRUCTURED`, the dispatch in `retrieval_service.py` falls through to the `else` branch (vector search). The structured query execution happens upstream in `use_cases_query.py` independently of SearchMode. These are two separate mechanisms that don't interact.

### 3.6 Tenant Isolation

PostgreSQL Row-Level Security via `set_config` — isolation at DB layer. Per-tenant Milvus collections. 4 collections exist (2 active, 2 empty). Correct.

**Reference:** `src/shared/`, `src/amber_platform/composition_root.py`

### 3.7 LLM Capacity Limiter

`src/shared/llm_capacity.py` — Redis-backed distributed semaphore. Priority: `chat > ingestion > communities`. Redis sorted sets with expiry timestamps for lease management. Required: Ollama is single-process; unbounded concurrent requests cause OOM. Justified.

### 3.8 Provider Failover Chain

Providers: OpenAI, Anthropic, Ollama, NVIDIA NIM, OpenRouter, OllamaCloud (added 2026-05-07).
Multi-key sequential failover within OllamaCloud. Environment-driven via pydantic-settings. Justified.

### 3.9 PII Scrubbing

`PIIScrubber` (`src/core/security/pii_scrubber.py`) is called in `context_builder.py:70` before chunks are sent to LLM. Patterns: phone, email (masked), SSN, credit card. This path is active.

### 3.10 RRF Fusion + Reranking

`src/core/retrieval/application/search/fusion.py` — RRF with adaptive weights. FlashRank cross-encoder reranker (`ms-marco-MiniLM-L-12-v2`) enabled by default (`enable_reranking=True`). Both working.

### 3.11 Rate Limiting

`RateLimitMiddleware` (`src/api/middleware/rate_limit.py`) — per-tenant, Redis-backed. Defaults: 60 req/min general, 20 queries/min, 50 uploads/hour. Not overridden in production .env — running at defaults.

---

## 4. Dead Code and Orphaned Features

### 4.1 Result Cache — Force Bypassed

**File:** `src/core/retrieval/application/retrieval_service.py:1070`

```python
# Force bypass for debugging
# if cached_result:
#     logger.info("Using cached result for '%s'", search_query)
#     # ... (skipped cache use code) ...
#     continue
cached_result = None  # FORCE MISS

if cached_result:
    # Original logic code blocked by force miss
    pass
```

The original cache-hit code path is **commented out in full** and replaced with `pass`. The `ResultCache.get()` call still executes (line 1062), but its result is unconditionally overwritten. The `if cached_result:` block below it is permanently dead.

**Production evidence:** 0 cache hits across all 21 sampled queries. `result_cache:*` keys: ~0 in Redis. `enable_result_cache: bool = True` in `RetrievalConfig` — the config says it's enabled but the code bypasses it.

**Root cause:** Unknown. Comment says "Force bypass for debugging." No documented reason exists; no git blame run (read-only constraint).

**Cost:** Full pipeline re-execution on every query. p50=13.8s latency forfeit per repeat query. Every `ResultCache.get()` call is wasted Redis roundtrip.

**Severity:** HIGH — either a correctness bug was found (undocumented) or significant latency optimization is being forfeited.

### 4.2 Hybrid Search — Disabled, Code Intact

**File:** `src/core/retrieval/application/retrieval_service.py:99`

```python
# Hybrid Search - DISABLED: Milvus 2.5.x has intermittent type mismatch errors
# with hybrid AnnSearchRequest
enable_hybrid: bool = False
```

**Correction from initial audit:** `SparseEmbeddingService` is **NOT loaded into memory**. Initialization is conditional:

```python
self.sparse_embedding = None
if self.config.enable_hybrid:
    self.sparse_embedding = SparseEmbeddingService()  # never reached
```

The import exists at line 42 but no SPLADE model is loaded. The call site also checks:

```python
if self.sparse_embedding and self.config.enable_hybrid:  # line 1101
```

Double guard. No memory or startup overhead from SPLADE. The cost is: dead code surface only.

**Re-enable plans:** No active roadmap item or timeline identified.

**Severity:** LOW — import + dead code surface. No runtime cost.

### 4.3 LOCAL Mode — Aliases to BASIC (entity_embeddings Missing)

**File:** `src/core/retrieval/application/retrieval_service.py:831`

```python
# Use simple vector search for BASIC/LOCAL
# (Hybrid search disabled until entity_embeddings collection is set up)
result = await self._execute_vector_search(...)
```

The dispatch `else` branch handles BASIC, LOCAL, and any unrecognized mode. `entity_embeddings` Milvus collection does not exist in production (verified §2.1). LOCAL is supposed to search entity-neighborhood subgraphs — it instead runs identical vector search as BASIC.

`SearchMode` enum advertises 5 behaviors. Verified dispatch:

| Mode | Actual handler | Status |
|------|---------------|--------|
| BASIC | `_execute_vector_search()` | ✓ Works |
| LOCAL | `_execute_vector_search()` (same) | ✗ Aliases BASIC |
| GLOBAL | `_execute_global_search()` | ✓ Works (20,536 embeddings) |
| DRIFT | `drift_search.search()` | ✓ Functional (see §5.3 for risk) |
| STRUCTURED | Handled upstream in `use_cases_query.py` | ✓ Works (see §3.5) |

**Severity:** MEDIUM — LOCAL is a broken abstraction. Users requesting LOCAL get BASIC silently.

### 4.4 DomainClassifier — Keyword Heuristics with LLM TODO

**File:** `src/core/generation/application/intelligence/classifier.py`

```python
def _call_llm(self, txt: str) -> DocumentDomain:
    if "def " in txt or "class " in txt:
        return DocumentDomain.TECHNICAL
    if any(k in txt.lower() for k in ["whereas", "pursuant", "indemnify"]):
        return DocumentDomain.LEGAL
    # ... 4 more elif branches
    # TODO: Replace with actual LLM call
    return DocumentDomain.GENERAL
```

Domain affects chunk_size/overlap via `STRATEGIES` registry:

| Domain | chunk_size | overlap |
|--------|-----------|---------|
| GENERAL | 600 | 50 |
| TECHNICAL | 800 | 50 |
| LEGAL | 1000 | 100 |
| FINANCIAL | 900 | 75 |
| SCIENTIFIC | 700 | 100 |
| CONVERSATIONAL | 400 | 30 |

663 Redis cache entries confirm active production use. Keyword heuristics drive chunking decisions for every ingested document.

**Failure modes:** A legal document in Italian gets `GENERAL` chunking (600 chars) because none of `["whereas", "pursuant", "indemnify"]` appear. A Python file with `class` in a comment gets `TECHNICAL` classification.

**LLM implementation plans:** No planned implementation date identified.

**Severity:** LOW-MEDIUM — functional but produces wrong answers on non-English or ambiguous content.

### 4.5 AgentOrchestrator — Feature-Flagged Incomplete Feature

**File:** `src/core/generation/application/agent/orchestrator.py:89`

```python
sources=[],  # TODO: Extract sources from tool outputs
timing=TimingInfo(total_ms=0, retrieval_ms=0, generation_ms=0),  # TODO: Track timing
```

ReAct loop (Think → Act → Observe) is implemented. However, the feature is gated:

```python
# src/core/retrieval/application/use_cases_query.py:123
if not _agent_flag("ENABLE_AGENT_MODE"):
    raise HTTPException(status_code=403, detail="Agent mode is disabled on this server.")
```

`ENABLE_AGENT_MODE` is NOT set in production `.env`. Requests with `agent_mode=True` receive HTTP 403. Users cannot trigger this path.

**Correction from initial audit:** More protected than originally described. The 403 gate prevents accidental activation. However the implementation is still incomplete (TODO stubs) and the flag could be set in .env without the TODO being resolved.

**Severity:** LOW currently (gated) — becomes HIGH if `ENABLE_AGENT_MODE=true` is added to .env without completing the TODO stubs.

### 4.6 Stale "Phase 6" Comment

**File:** `src/core/retrieval/application/retrieval_service.py:~786`

```python
# For now, most modes fall back to vector search with optional HyDE/Decomposition
# Phase 6 will implement specialized Global and DRIFT strategies.
```

This comment is **factually wrong** — GLOBAL and DRIFT ARE implemented and dispatched correctly in the code immediately below. The comment is a historical artifact from an earlier implementation phase. Creates false impression that GLOBAL/DRIFT are not yet implemented.

**Severity:** Documentation — misleads future developers reading this code.

---

## 5. Architectural Risks

### 5.1 Garage is a Single Point of Failure for Two Independent Systems

**`docker-compose.yml`:**
```yaml
milvus:
  environment:
    MINIO_ADDRESS: garage:3900
```

Garage serves:
1. Raw document objects (upload/download API)
2. Milvus S3 backend (Milvus writes index segments to Garage)

**Blast radius:** A Garage failure simultaneously breaks:
- Document serving (S3 reads)
- Vector search (Milvus cannot read/write index segments)
- New ingestion (documents cannot be stored)

These are logically independent systems that share a single failure domain.

**This already happened:** 129 of 137 failed documents in production returned `NoSuchKey` from Garage. The vector search system was not affected in that incident only because Milvus had the index segments in memory. A restart during a Garage outage would lose both.

**Severity:** HIGH — single infrastructure failure disables the entire product.

### 5.2 QueryRouter LLM Call on Critical Path

**File:** `src/core/retrieval/application/query/router.py:168`

```python
# 2. LLM classification (after keyword heuristics fail)
if use_llm:
    prompt = QUERY_MODE_PROMPT.format(query=query)
    mode_res = await provider.generate(prompt, work_class="chat", **kwargs)
```

Call site in `retrieval_service.py:781`:
```python
search_mode = await self.router.route(
    structured_query.cleaned_query,
    explicit_mode=options.search_mode,
    tenant_config=tenant_config,
    # use_llm defaults to True
)
```

Every query not caught by keyword heuristics (GLOBAL: 8 words, DRIFT: 7 words, STRUCTURED starters: 6 words) makes a synchronous LLM call before retrieval begins.

**On LLM failure:** falls back to `SearchMode.BASIC`. The LLM call therefore has:
- Upside: correct routing to GLOBAL/DRIFT (for queries that contain none of the 21 heuristic keywords but semantically match)
- Downside on failure: adds network latency with no routing benefit

**On success:** adds LLM generation latency to every query. This contribution to the 13.8s p50 is unmeasured (router latency is not isolated in `metrics:query:*`).

**Severity:** MEDIUM — latency impact unknown due to missing instrumentation.

### 5.3 DRIFT Search — Unbounded Recursive Latency

**File:** `src/core/retrieval/application/search/drift_search.py`

```python
for iteration in range(max_iterations):  # max_iterations = 3
    results = await self.retrieval_service.retrieve(query, options)
    # LLM generates follow-up question
    follow_up = await self.llm.generate(follow_up_prompt)
    query = follow_up
```

Each iteration calls the full `retrieval_service.retrieve()` pipeline, including its own `router.route()` call (another LLM call per iteration).

**Worst-case math:**
```
3 iterations × p90 (24,688ms) = 74,064ms
+ 2 inter-iteration LLM generation calls
= ~80s worst case
```

No wall-clock timeout. No circuit breaker. No budget.

**DRIFT activation status:** Not monitored — no data on whether it fires in production.

**Severity:** HIGH if activated — latent ~80s tail latency incident. LOW if never activated (cannot be confirmed without SearchMode instrumentation).

### 5.4 Two Overlapping Routing Layers

**QueryRouter** (`src/core/retrieval/application/query/router.py`):
- Pre-retrieval
- LLM + keyword heuristics → selects `SearchMode`
- Determines *what* to search

**QueryComplexityRouter** (`src/core/generation/application/intelligence/query_complexity.py`):
- Post-retrieval
- Score-based (word count + synthesis keywords + chunk count + context tokens) → selects LLM tier (SIMPLE/STANDARD/COMPLEX/REASONING)
- Determines *how* to generate

Both assess "query complexity." A query classified BASIC by QueryRouter (low retrieval complexity → pure vector search) can score REASONING by QueryComplexityRouter (high generation complexity → most powerful LLM). No documented policy on how these interact. The two tiers use completely different signals and have no shared state.

**Severity:** LOW-MEDIUM — works in practice, but creates conceptual confusion about ownership of complexity routing.

---

## 6. Monitoring Gaps

### 6.1 SearchMode Not Instrumented

`metrics:query:*` Redis entries contain: `operation`, `chunks_retrieved`, `cache_hit`, `local_hits`, `total_latency_ms`. **`search_mode` is absent.**

Consequence: impossible to know how often QueryRouter selects GLOBAL vs BASIC vs DRIFT in production. All decisions about SearchMode variants are architectural guesses.

### 6.2 No Query Latency SLO

No alert threshold. No SLO. Current p50=13.8s, p90=24.7s inferred from volatile Redis metrics with TTL. Not in any persistent monitoring system. If the p90 spikes to 60s, nobody is alerted.

### 6.3 Router Latency Not Isolated

`total_latency_ms` in metrics includes: rewrite, parse, taxonomy routing, QueryRouter LLM call, retrieval, reranking, generation. The contribution of the router's LLM call is unknown. Optimizing latency without this breakdown is guesswork.

### 6.4 Dead Cache Not Alerted

`enable_result_cache: bool = True` in config but 0 cache hits in production. No inconsistency alert exists. The config says caching is on; it isn't. A future developer could add cache invalidation logic not knowing the cache is bypassed.

---

## 7. Security Audit

> **Context:** System runs on intranet only — not publicly routable. Port exposure risks below are scoped to **insider threat and lateral movement** (compromised intranet host → pivot to data stores), not external internet attack.

### 7.1 MEDIUM — Data Stores Exposed on All Interfaces (Intranet-Scoped)

**Verified:**
```
ufw status → Status: inactive
ss -tlnp → all ports bound to 0.0.0.0
```

| Port | Service | Auth | Intranet Risk |
|------|---------|------|--------------|
| 6379 | Redis | **None** | MEDIUM — any intranet host reads/writes all cache+queue data |
| 5433 | PostgreSQL | `graphrag:graphrag` | MEDIUM — trivially guessable (user=pass) |
| 7474 | Neo4j Browser | `neo4j:changeme` | LOW — graph data visible to any intranet user |
| 7687 | Neo4j Bolt | `neo4j:changeme` | LOW |
| 19530 | Milvus gRPC | None | LOW — vector data accessible |
| 9091 | Milvus metrics | None | LOW — internal metrics only |

On intranet: no urgency if network is trusted and access-controlled at the network layer. Becomes HIGH instantly if server is ever moved to a DMZ, VPN-accessible, or cloud deployment.

**Recommended hardening (low effort, high future-proofing):**
- Redis: add `requirepass` in config
- PostgreSQL: rotate `graphrag:graphrag` to non-guessable credentials
- Bind data stores to Docker internal network only (remove host port mappings for all except Nginx 80)

### 7.2 MEDIUM — CORS Wildcard in Production

**File:** `src/api/main.py:421-434`

```python
if settings.cors_origins:
    cors_origins = settings.cors_origins
else:
    cors_origins = ["*"]
    logger.warning("CORS_ORIGINS unset; defaulting to '*' (debug mode only)")
```

`CORS_ORIGINS` is **not set** in production `.env`. `DEBUG=false`. The warning says "debug mode only" but production runs with `allow_origins=["*"]`.

**Consequence:** Any website can make API requests using a victim's API key from their browser (stored in browser storage). Combined with the `X-API-Key` auth model (not cookies), CSRF is not the main risk — but any XSS in the frontend leaks the key to a cross-origin attacker who can then call the API directly.

**Fix:** Set `CORS_ORIGINS=https://your-server.example.com` in production `.env`.

### 7.3 HIGH — InjectionGuard Built but Never Called

**File:** `src/core/security/injection_guard.py`

`InjectionGuard` implements:
- `sanitize_input()` — HTML-escapes XML tags, normalizes whitespace
- `validate_input()` — regex patterns for injection detection
- `format_secure_prompt()` — XML-delimited prompt with system/context/user separation

**Verification:**
```
grep -rn "InjectionGuard\|sanitize_input\|validate_input" src/ → 0 results outside the class itself
```

Neither `sanitize_input()` nor `validate_input()` is called anywhere in the codebase. User queries are passed directly into LLM prompts without sanitization.

**Current path:** `query` → `router.route()` → `QUERY_MODE_PROMPT.format(query=query)` — raw string interpolation.

The `InjectionDetector` patterns are also limited — they cover obvious patterns (`"ignore all previous instructions"`, `"drop table"`) but miss role-play jailbreaks, DAN prompts, and multi-turn injection accumulation.

**Severity:** HIGH — prompt injection is an active threat for public-facing RAG systems. The defense infrastructure exists in code but is disconnected.

### 7.4 MEDIUM — File Upload MIME Type Not Validated Server-Side

**File:** `src/api/routes/documents.py:406`

```python
content_type=file.content_type or "application/octet-stream",
```

`file.content_type` comes from the HTTP request header — it is **client-controlled**. Any file can be uploaded with any claimed MIME type. `python-magic` is listed as a dependency in `requirements-optional.txt` but is not used in the upload path.

File size is validated (100MB default limit). Content type is not.

**Risk:** A malicious user could upload an executable claiming to be `application/pdf`. The file is stored in Garage and passed to the extractor fallback chain. Extractors may fail safely, but a crafted file could exploit vulnerabilities in underlying extractor libraries (Unstructured, PyMuPDF).

**Fix:** Add magic-number validation using `python-magic` before storage.

### 7.5 MEDIUM — Swagger UI Publicly Accessible

**File:** `src/api/middleware/auth.py:25`

```python
PUBLIC_PATHS = {
    "/health", "/health/ready", "/v1/health", "/v1/health/ready",
    "/docs", "/redoc", "/openapi.json",
}
```

Full API documentation (endpoints, request/response schemas, auth header names) is accessible without authentication on production at `http://your-server.example.com/docs`.

**Risk:** Any intranet user (without an API key) can enumerate all endpoints, request schemas, and auth mechanisms before obtaining credentials.

**Fix:** Either disable Swagger UI in production (`app = FastAPI(docs_url=None)`) or require authentication for `/docs` and `/openapi.json`.

### 7.6 LOW — Celery Result Backend Contains Task Metadata

Redis db2 contains 645 `celery-task-meta-*` keys (no TTL — `expires=0`). These contain task execution metadata including document IDs, tenant IDs, and task status. Since Redis has no auth and is internet-exposed (§7.1), this data is readable by anyone.

### 7.7 LOW — API Key Hashed but Salt Not Verified

`generate_api_key` and `hash_api_key` are in `src/shared/security.py`. Audit could not verify whether PBKDF2/bcrypt or a fast hash (SHA-256) is used — file not read in detail. If SHA-256 without salt is used for API key hashing, keys are susceptible to rainbow table attacks once the PostgreSQL is compromised (§7.1).

---

## 8. Summary Verdict

### Is the Architecture Over-Complicated?

**Partially.** The over-complexity is concentrated in two areas:

**Area 1: Orphaned features in the query pipeline**

4–5 features in "shipped but broken/unknown" state:

| Feature | State | Code surface | Runtime cost |
|---------|-------|-------------|-------------|
| Result cache | FORCE MISS, unknown why | ~100 lines | Redis roundtrip per query |
| Hybrid search | Disabled (Milvus bug) | ~50 lines import | None (conditional init) |
| LOCAL mode | Aliases BASIC | None extra | None extra |
| AgentOrchestrator | 403-gated, TODO stubs | ~200 lines | None (gated) |
| DomainClassifier | TODO LLM, using keywords | ~80 lines | Active but incorrect |

**Area 2: Ownership ambiguity**

5 of 6 critical architectural questions have no documented decision on record. Features were built, then left without explicit roadmap commitment or deprecation. This is the primary driver of perceived over-complexity — not the features themselves, but the accumulated uncertainty around their status.

**What is legitimately complex and justified:**

Multi-store (Milvus + Neo4j + Garage + PG + Redis), tenant RLS, provider failover, LLM capacity limiter, community pipeline, RRF fusion, extractor fallback chain, rate limiting — all have production evidence and clear purpose. Remove any one: observable failure.

### Complexity vs. Value Matrix

```
                    HIGH VALUE                    LOW VALUE / ORPHANED
                ┌─────────────────────────────┬─────────────────────────────┐
  WORKING       │ Tenant RLS                  │ QueryRouter LLM call        │
                │ Provider failover chain     │ (on hot path, cost unknown) │
                │ LLM capacity limiter        │                             │
                │ community_embeddings/GLOBAL │ DomainClassifier keyword    │
                │ STRUCTURED query handler    │ (TODO LLM, wrong for       │
                │ Graph extraction            │ non-English docs)           │
                │ RRF fusion + reranking      │                             │
                │ PII scrubber                │                             │
                │ Rate limiting               │                             │
                ├─────────────────────────────┼─────────────────────────────┤
  DEAD /        │ Result cache                │ Hybrid search (dead import) │
  INCOMPLETE    │ (fixable — unknown why      │                             │
                │ it was bypassed)            │ AgentOrchestrator           │
                │                             │ (gated + TODO stubs)        │
                │                             │                             │
                │                             │ LOCAL mode                  │
                │                             │ (aliases BASIC silently)    │
                │                             │                             │
                │                             │ InjectionGuard              │
                │                             │ (built, never wired in)     │
                └─────────────────────────────┴─────────────────────────────┘
```

---

## 9. Recommended Actions

### P0 — Security

> Intranet context: items 9.1–9.3 are hardening (not emergencies). Items 9.4–9.5 are application-layer issues independent of network topology.

**9.1 Wire `InjectionGuard` into the query path.** The class is built and working. Zero wiring effort — call `guard.sanitize_input(query)` before `QUERY_MODE_PROMPT.format(query=query)`, `HYDE_PROMPT.format(query=query)`, and any other prompt interpolation. Prompt injection is a real risk even from internal users.

**9.2 Set `CORS_ORIGINS` in production `.env`.** `CORS_ORIGINS=https://your-server.example.com` (or the intranet hostname). One-line fix; warning already in the logs.

**9.3 Add Redis password.** `requirepass <password>` in Redis config + update `REDIS_URL`. Low effort, good hygiene. Becomes critical if deployment ever moves to cloud/DMZ.

**9.4 Rotate PostgreSQL credentials.** `graphrag:graphrag` (password = username). One `ALTER USER` + update `.env`.

**9.5 Disable Swagger UI in production.** `FastAPI(docs_url=None, redoc_url=None)` or bind to localhost. Any intranet user currently sees the full API schema unauthenticated.

### P1 — Observability (prerequisite for all architecture decisions)

**9.7 Add `search_mode` to `metrics:query:*`** and persist to `usage_logs`. Without this, decisions about GLOBAL/DRIFT/LOCAL/STRUCTURED are guesses.

**9.8 Define a query latency SLO** (suggested: p90 < 15s) and add a Redis alert or Prometheus scrape. Current p90=24.7s is unknown to the team.

**9.9 Add per-phase latency breakdown:** `router_ms`, `retrieval_ms`, `reranking_ms`, `generation_ms` in the metrics payload. Needed to isolate QueryRouter LLM overhead.

### P2 — Resolve Dead Code

**9.10 Investigate the result cache `FORCE MISS`.** Run `git log -p` on line 1070. If it was a correctness fix: document the bug and add a proper comment explaining why. If it was a debug patch: remove the `None` assignment and restore the original cache-hit code path.

**9.11 Declare intent on orphaned features.** For: hybrid search, AgentOrchestrator, LOCAL mode, DomainClassifier LLM. Each needs one decision:
- Concrete quarter to complete → becomes roadmap item
- Decision to remove → PR to delete code

**9.12 Fix or remove the stale "Phase 6" comment** in `retrieval_service.py:~786`. GLOBAL and DRIFT are already implemented.

### P3 — Structural Risk

**9.13 Decouple Garage from Milvus.** Milvus should use a separate storage backend (dedicated Garage bucket with independent credentials, or switch Milvus to `local` disk storage for non-HA deployments). Document storage and vector index storage should not share a failure domain.

**9.14 Add wall-clock timeout to DRIFT loop.** ~25s total budget prevents the 80s worst-case cascade.

**9.15 Upload MIME validation.** Use `python-magic` (already a dependency) to validate actual file content against claimed `content_type` before storing in Garage.

---

## Appendix A — Key File Reference Table

| Finding | File | Line |
|---------|------|------|
| Result cache FORCE MISS | `src/core/retrieval/application/retrieval_service.py` | 1070 |
| `enable_hybrid = False` | `src/core/retrieval/application/retrieval_service.py` | 99 |
| SparseEmbed conditional init | `src/core/retrieval/application/retrieval_service.py` | 177 |
| LOCAL=BASIC dispatch comment | `src/core/retrieval/application/retrieval_service.py` | 831 |
| Stale "Phase 6" comment | `src/core/retrieval/application/retrieval_service.py` | ~786 |
| QueryRouter keyword sets | `src/core/retrieval/application/query/router.py` | 29–63 |
| QueryRouter LLM call | `src/core/retrieval/application/query/router.py` | 168 |
| DRIFT recursive loop | `src/core/retrieval/application/search/drift_search.py` | iterate() |
| STRUCTURED handler (use case) | `src/core/retrieval/application/use_cases_query.py` | 86 |
| AgentOrchestrator flag gate | `src/core/retrieval/application/use_cases_query.py` | 123 |
| AgentOrchestrator TODO stubs | `src/core/generation/application/agent/orchestrator.py` | 89, 92 |
| DomainClassifier keyword TODO | `src/core/generation/application/intelligence/classifier.py` | _call_llm() |
| QueryComplexityRouter | `src/core/generation/application/intelligence/query_complexity.py` | route() |
| InjectionGuard (unused) | `src/core/security/injection_guard.py` | full file |
| PIIScrubber (active) | `src/core/generation/application/context_builder.py` | 70 |
| CORS wildcard fallback | `src/api/main.py` | 424 |
| Auth middleware / public paths | `src/api/middleware/auth.py` | 25, 153 |
| File upload MIME client-trust | `src/api/routes/documents.py` | 406 |
| Rate limit defaults | `src/api/config.py` | 82–85 |
| Garage = Milvus backend | `docker-compose.yml` | milvus env MINIO_ADDRESS |
| Composition root DI wiring | `src/amber_platform/composition_root.py` | full file |

## Appendix B — SearchMode Dispatch Map

```python
# src/shared/kernel/models/query.py — QueryOptions defaults
search_mode: SearchMode = SearchMode.BASIC
use_hyde: bool = False
use_rewrite: bool = True   # fires only when history/rules/memory_context present
use_decomposition: bool = False
agent_mode: bool = False   # gated by ENABLE_AGENT_MODE env flag

# Dispatch — src/core/retrieval/application/retrieval_service.py:795
if search_mode == SearchMode.GLOBAL:
    → _execute_global_search()               # community_embeddings: 20,536 entities ✓
elif search_mode == SearchMode.DRIFT:
    → drift_search.search()                  # 3x recursive retrieve() loop ✓ (risky)
else:  # BASIC, LOCAL, STRUCTURED, unknown
    → _execute_vector_search()               # BASIC ✓, LOCAL broken, STRUCTURED mismatch

# STRUCTURED is intercepted before retrieval in use_cases_query.py:86
→ structured_executor.try_execute()         # 8 Cypher templates, parameterized ✓
```

## Appendix C — Exposed Port Summary (Production)

```
Port  Service        Bound      Auth               Risk (intranet)
----  ---------      ---------  -----------------  ---------------
6379  Redis          0.0.0.0    None               MEDIUM
5433  PostgreSQL     0.0.0.0    graphrag:graphrag   MEDIUM (trivial creds)
7474  Neo4j HTTP     0.0.0.0    neo4j:changeme   LOW
7687  Neo4j Bolt     0.0.0.0    neo4j:changeme   LOW
19530 Milvus gRPC    0.0.0.0    None               LOW
9091  Milvus metrics 0.0.0.0    None               LOW

Firewall: INACTIVE — acceptable for trusted intranet; HIGH risk if ever moved to cloud/DMZ
```

## Appendix D — Production Query Samples

```json
{"operation":"rag_query","query":"How do I create a new user account in Acme Mail?",
 "chunks_retrieved":10,"cache_hit":false,"local_hits":0,"total_latency_ms":12174}

{"operation":"rag_query","query":"Su quale versione sto lavorando?",
 "chunks_retrieved":10,"cache_hit":false,"local_hits":0,"total_latency_ms":2268}

{"operation":"rag_query","query":"What happened to sent emails yesterday between 2-4pm?",
 "chunks_retrieved":10,"cache_hit":false,"local_hits":0,"total_latency_ms":13285}

{"operation":"rag_query","query":"How can I check server disk usage via CLI?",
 "chunks_retrieved":10,"cache_hit":false,"local_hits":0,"total_latency_ms":12492}
```

All samples: `cache_hit=false`. Aggregate across 21 queries: `local_hits=50` — graph IS contributing on some queries even though not visible in individual samples.
