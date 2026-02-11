# Graph Sync Performance Optimization Plan (v2)

## 1. Problem Statement and Measurable Targets

### Baseline (from worker logs)

Observed run: document `doc_9dd39a9214454531` (55 chunks), cloud Ollama (`devstral-small-2:24b`).

| Metric | Baseline |
|--------|----------|
| Chunks observed | 30 / 55 |
| Total wall-clock | 31.6 min |
| Throughput | 0.95 chunks/min |
| Effective seconds per LLM call | 31.6s |
| LLM calls | 60 (2 per chunk) |

Key finding: LLM inference dominates wall-clock time on both cloud and local profiles. Neo4j write cost is secondary.

### Success criteria

| Goal | Target |
|------|--------|
| First-run throughput gain (cloud) | >= 30% |
| First-run throughput gain (local_weak profile) | >= 40% |
| Re-run LLM call reduction with cache | >= 95% |
| Extraction quality regression | <= 2 percentage points vs baseline on validation corpus |
| Graph sync failure rate | < 1% |

## 2. Decisions and Scope

### Approved decisions

1. Keep single pipeline worker flow. Do not split into `prepare/llm/write` Celery queues.
2. Optimize for low-risk changes first: instrumentation, semaphore scope fix, deterministic gleaning gate, cache.
3. Defer adaptive concurrency until static-profile improvements are validated.
4. Keep multi-endpoint routing out of scope for this iteration.

### Out of scope for v2

1. Per-chunk endpoint/model routing.
2. Per-document mega-gleaning prompt.
3. Full graph writer redesign beyond targeted batching experiments.

## 3. Revised Phase Order

### Phase 0: Instrumentation and quality harness (mandatory gate)

Files:
- `src/core/graph/application/processor.py`
- `src/core/ingestion/infrastructure/extraction/graph_extractor.py`

Changes:
1. Add structured chunk-level and document-level metrics.
2. Emit extract wait time, extract duration, gleaning duration, write duration, cache hit, errors.
3. Add fixed validation corpus and scoring script for extraction quality.

Acceptance criteria:
1. Metrics present for >= 99% of chunks in benchmark runs.
2. Quality baseline captured and versioned before optimization rollout.

### Phase 1: Free semaphore earlier + static profile concurrency

Files:
- `src/core/graph/application/processor.py`
- `src/workers/tasks.py`
- `src/amber_platform/composition_root.py`
- `config/settings.yaml`

Changes:
1. Move `write_extraction_result` outside LLM semaphore critical section.
2. Replace hardcoded `Semaphore(5)` with profile-based static concurrency:
`local_weak=1`, `cloud_strong=3`, `default=3`.
3. Wire extractor config (`use_gleaning`, thresholds) from settings instead of hardcoding.

Acceptance criteria:
1. Throughput improves >= 8% on cloud baseline document.
2. No increase in write failures or duplicate graph records.
3. Local profile confirms no queued parallel LLM calls (`effective_concurrency ~= 1`).

### Phase 2: Extraction cache (safe keying and tenant isolation)

Files:
- `src/core/ingestion/infrastructure/extraction/extraction_cache.py` (new)
- `src/core/ingestion/infrastructure/extraction/graph_extractor.py`

Changes:
1. Add Redis-backed cache for final extraction result.
2. Cache key must include:
`tenant_id`, `chunk_hash`, `prompt_hash`, `ontology_hash`, `model`, `temperature`, `seed`, `gleaning_mode`, `extractor_version`.
3. Add TTL config (`cache_ttl_hours`, default 168).

Feature flag:
- `GRAPH_SYNC_CACHE_ENABLED=false` by default for first deployment.

Acceptance criteria:
1. Reprocessing same document reduces LLM calls by >= 95%.
2. Zero cross-tenant cache leakage in tests.
3. Cache deserialization errors < 0.1%.

### Phase 3: Smart gleaning v1 (deterministic gate, quality-first)

Files:
- `src/core/ingestion/infrastructure/extraction/graph_extractor.py`
- `src/core/generation/application/prompts/entity_extraction.py`

Changes:
1. Replace always-on gleaning with deterministic trigger rules. Example:
run gleaning only when pass-1 entity/relationship yield is low or parse confidence is low.
2. Optional model-reported `COVERAGE` can be logged, but not used as sole gate.
3. Add per-chunk reason codes: `gleaning_run_reason` or `gleaning_skip_reason`.

Feature flag:
- `GRAPH_SYNC_SMART_GLEANING=false` by default for first deployment.

Acceptance criteria:
1. First-run LLM calls reduced >= 25% on benchmark corpus.
2. Quality regression <= 2 percentage points overall and <= 3 points in any domain slice.
3. Manual review sample passes (20 documents, no critical misses).

### Phase 4: Adaptive concurrency governor (experimental)

Files:
- `src/core/graph/application/concurrency_governor.py` (new)
- `src/core/graph/application/processor.py`

Changes:
1. Introduce adaptive controller with hysteresis and cooldown.
2. Enforce bounds (`min=1`, `max=5`) for initial rollout.
3. Emit governor state transitions in logs.

Feature flag:
- `GRAPH_SYNC_ADAPTIVE_CONCURRENCY=false` by default.

Acceptance criteria:
1. Beats best static profile throughput by >= 10% in both local and cloud tests.
2. No instability (<= 2 limit changes per 100 chunks after warmup).
3. No increase in timeout/error rates.

### Phase 5: Neo4j batching (only if bottleneck remains)

Files:
- `src/core/graph/application/writer.py`
- `src/core/graph/infrastructure/neo4j_client.py`

Changes:
1. Batch relationship writes in fewer transactions.
2. Keep community staleness behavior unchanged.

Acceptance criteria:
1. `write_ms` p95 drops by >= 20%.
2. End-to-end throughput gain >= 3%. If not, do not ship.

## 4. Rollout and Guardrails

### Flag policy

| Flag | Default | Rollout order |
|------|---------|---------------|
| Instrumentation | true | Phase 0 |
| `GRAPH_SYNC_CACHE_ENABLED` | false | After Phase 2 passes |
| `GRAPH_SYNC_SMART_GLEANING` | false | After Phase 3 quality gate passes |
| `GRAPH_SYNC_ADAPTIVE_CONCURRENCY` | false | Experimental only |

### Rollout stages

1. Internal tenants only.
2. 10% tenant canary.
3. 50% tenants.
4. 100% rollout.

Stop and rollback if any of these trigger:
1. Quality regression exceeds thresholds.
2. Graph sync failure rate >= 1%.
3. P95 document latency worsens by >= 15% for two consecutive runs.

## 5. Metrics Schema (required)

### Per chunk

```json
{
  "event": "graph_sync_chunk_metrics",
  "document_id": "doc_x",
  "chunk_id": "chunk_y",
  "extract_wait_ms": 0,
  "extract_ms": 28000,
  "gleaning_ms": 0,
  "write_ms": 450,
  "llm_calls": 1,
  "entities": 24,
  "relationships": 18,
  "cache_hit": false,
  "gleaning_run_reason": "low_entity_yield",
  "error": null
}
```

### Per document

```json
{
  "event": "graph_sync_document_metrics",
  "document_id": "doc_x",
  "total_chunks": 55,
  "total_ms": 1200000,
  "chunks_per_minute": 2.75,
  "llm_calls_total": 74,
  "cache_hits": 22,
  "gleaning_skipped": 31,
  "config_profile": "cloud_strong",
  "concurrency_mode": "static"
}
```

## 6. Verification Plan

### Automated tests

```bash
pytest tests/unit/graph/test_extraction_cache.py -v
pytest tests/unit/graph/test_smart_gleaning_rules.py -v
pytest tests/unit/graph/test_processor_concurrency_scope.py -v
pytest tests/integration/test_graph_sync_metrics.py -v
pytest tests/integration/test_graph_sync_quality_regression.py -v
```

### Benchmark protocol

1. Run baseline on fixed corpus with current main branch.
2. Run each phase independently behind flags.
3. Record throughput, LLM calls, write latency, failure rate, quality score deltas.
4. Promote only phases that satisfy acceptance criteria.

## 7. Concrete Implementation Checklist

1. [x] Implement Phase 0 metrics and quality harness.
2. [x] Implement Phase 1 semaphore-scope fix and static profile config.
3. [x] Implement Phase 2 cache with strict keying and tenant isolation tests.
4. [x] Implement Phase 3 smart gleaning deterministic rules and quality gates.
5. [x] Evaluate whether Phase 4 is still necessary after Phase 1-3.
6. [x] Run Phase 5 only if write path shows measurable residual bottleneck.

Decision note: Phase 4 remains experimental and is implemented as opt-in (`adaptive_concurrency_enabled=false` by default).
Decision note: Phase 5 batching is implemented. Throughput impact benchmark is pending infrastructure-backed integration execution.

## 8. Notes from Prior Discussion (kept)

1. Local Ollama is a stronger bottleneck, but cloud throughput is also constrained by LLM latency.
2. Splitting into multiple Celery stage queues is complexity without commensurate benefit.
