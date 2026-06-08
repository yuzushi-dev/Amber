<claude-mem-context>
# Memory Context

# [Amber] recent context, 2026-05-18 9:58am GMT+2

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 21 obs (6,750t read) | 522,724t work | 99% savings

### May 15, 2026
596 2:00p 🔵 PRs Documentation Directory Structure in Amber Project
597 " 🔵 Amber 2.0 PR Batch Review: 8/10 Audit PRs Completed, 2 Correctly Deferred
598 " 🔵 PR-01 Result Cache Restoration Verified in Source Code
599 " 🔵 PR-03 InjectionGuard Wiring Verified: sanitize_input Called in router.py and hyde.py
600 " 🔵 PR-04 Search Mode + Router Latency Metrics Verified Propagated End-to-End
601 " 🔵 Amber 2.0 Production Telemetry: p50=13.8s, 0% Cache Hits, SearchMode Unmonitored
602 " 🔵 Amber 2.0 Security Posture: InjectionGuard Disconnected, CORS Wildcard, Swagger Public
603 " ⚖️ PR-02 (CORS) and PR-09 (DomainClassifier LLM) Deliberately Deferred
S70 PR quality review of /docs/PRs — evaluate 10 audit PRs and 5 local fixes, identify which 2 were intentionally deferred and assess their quality (May 15, 2:02 PM)
608 2:29p 🔵 Retrieval Service Multi-Modal Search Architecture
609 " 🔵 Prompt Guard / Prompt Injection Protection Not in Amber Dependencies
610 " 🟣 Router Latency Instrumentation Added to Retrieval Pipeline
611 " 🔵 RetrievalResult Constructed in Four Places in retrieval_service.py
612 2:30p 🔵 DRIFT Search Path Missing router_latency_ms in RetrievalResult
613 2:36p 🔵 Amber Project: Active Multi-Component Modification Snapshot
614 2:37p 🔵 Amber PR Unit Test Suite: All 31 Tests Passing
615 " 🟣 PR-03: InjectionGuard Replaced with prompt-guard Library
616 " 🟣 PR-04: Search Mode and Router Latency Metrics Added
617 " 🟣 PR-05: DRIFT Search Timeout with Deadline Tracking
618 " ✅ PR-06: Stale Comment Removed and LOCAL Mode Warning Added
619 " ✅ TICKETS.md Solution Notes Refined with Precise Implementation Details
620 " 🔴 PR-08: Swagger UI Default Corrected to False, openapi_url Also Gated
S71 Amber 2.0 architecture audit PR implementation — finalizing 8 completed PRs with tests passing and documentation synchronized (May 15, 2:38 PM)
**Investigated**: The full TICKETS.md backlog (10 audit PRs + 5 local fixes), git diff --stat showing actual file changes, all 6 PR unit test files, and specific implementation details across retrieval_service.py, injection_guard.py, drift_search.py, use_cases_documents.py, config.py, and main.py

**Learned**: - enable_docs defaults to False (not True) — Swagger, ReDoc, and openapi_url all gated; production requires no action
    - PR-06 removed TWO Phase 6 comments: one at ~line 786 in routing logic, one at line 217 in __init__ ("Phase 6 &amp; Graph Searchers")
    - Router timing pinned to retrieval_service.py:783 with perf_counter; propagation via result.search_mode = search_mode.value and result.router_latency_ms = _router_latency_ms
    - prompt-guard dependency properly added to requirements.txt (not just a git install command)
    - Actual git diff shows 15 files changed, +184/-89 lines (slightly more than originally documented as 14 files +177/-88)
    - 31/31 unit tests pass across all 6 PR test files

**Completed**: - PR-01: Result cache restored — removed FORCE MISS bypass, latency ~14s → &lt;100ms for cache hits
    - PR-03: InjectionGuard rewired with prompt-guard library (840+ patterns), singleton wired in router.py and hyde.py before prompt interpolation
    - PR-04: search_mode and router_latency_ms added to QueryMetrics + RetrievalResult, propagated through pipeline to Redis metrics:query:* keys
    - PR-05: DRIFT search timeout (25s default) with asyncio deadline tracking and per-call wait_for protection
    - PR-06: Two stale Phase 6 comments removed; LOCAL mode now logs warning with tenant_id when entity_embeddings collection missing
    - PR-07: Server-side MIME validation via python-magic.from_buffer() on first 4096 bytes, graceful fallback if library absent
    - PR-08: Swagger/ReDoc/openapi_url gated behind enable_docs=False default; ENABLE_DOCS=true required to enable
    - PR-10: Milvus decoupled from Garage S3 — now uses local graphrag-milvus Docker volume
    - PR-LOCAL-01 through PR-LOCAL-05: Nginx naming, GRAPHRAG_APP_PASSWORD, IGNORE_EMBEDDING_MISMATCH, huggingface-hub pin, LoadBalancedLLMProvider restored
    - TICKETS.md fully synchronized with actual implementation (line numbers, defaults, file counts, test pass rate)
    - All documentation corrections applied: 15 files/+184/-89, 31/31 tests, prompt-guard>=3.7.1 in requirements.txt

**Next Steps**: Session appears complete — all 8/10 audit PRs implemented and verified, documentation synchronized. Deferred: PR-02 (CORS_ORIGINS production .env change) and PR-09 (DomainClassifier LLM integration). Branch is ready for review/deployment.


Access 523k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>