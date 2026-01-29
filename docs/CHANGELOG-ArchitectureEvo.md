# Amber — ArchitectureEvo Release Changelog

**Branch:** `ArchitectureEvo` vs `main`  
**Period:** January 22 – January 29, 2026  
**Commits:** 73  
**Impact:** 498 files changed, 26,274 insertions, 17,371 deletions  

---

## Major Architecture Refactoring

This release represents a complete clean architecture transformation of the Amber platform. The codebase has been restructured following Domain-Driven Design principles with clear separation of concerns.

### Clean Architecture Implementation

- **Layered Structure**: Each core domain now follows the pattern: `domain` → `application` → `infrastructure`
- **Dependency Inversion**: Core modules no longer import from API/platform layers
- **Composition Root**: Centralized dependency wiring with lazy settings provider
- **Unit of Work Pattern**: Explicit tenant scoping via PostgreSQL session variables with single transaction boundary management

### Domains Restructured

| Domain     | Description                                                                                                 |
| ---------- | ----------------------------------------------------------------------------------------------------------- |
| Ingestion  | Document processing with extraction strategies (fallback, local, API-based), chunking logic, and connectors |
| Retrieval  | Query parsing, structured queries, hybrid search with sparse/dense embeddings, result fusion and re-ranking |
| Generation | Chat services with memory management (Redis/Postgres), context builder, and intelligence strategies         |
| Graph      | Entity extraction, communities, maintenance, and Neo4j integration                                          |
| Admin Ops  | Metrics, quality, tuning, evaluation, observability, and usage tracking                                     |
| Tenants    | Tenant isolation core with comprehensive verification scripts                                               |

---

## New Features

### LLM Configuration and Model Management

- LLM Step Catalog and Resolver: Define and customize LLM configurations for each processing step (ingestion, graph extraction, retrieval, generation)
- Provider Model Override: Allow specific models to be overridden per LLM provider
- Global Apply Feature: Apply LLM settings globally across all tenants from admin panel
- Embedding Settings Moved: Embedding configuration relocated from `/tuning` to `/llms` for better UX

### Vector Collection Management

- Active Vector Collection: Implement collection-aware document management with migration support
- Collection Migration: Safely migrate documents between vector collections with embedding regeneration

### User Interface Improvements

- Constellation Loader: New animated loader replacing circular spinner
- Infinite Scroll for Conversations: Sidebar conversation list now loads progressively
- Standardized Modal Designs: Consistent modal appearances across the application
- UI Kit Accessibility Fixes: Improved motion and accessibility compliance

### Document and Folder Management

- Bulk Delete: Select and delete multiple folders or documents simultaneously
- Folder Deletion Options: Enhanced deletion with content handling choices
- Real-time Stats Updates: UI automatically refreshes statistics after document/folder actions

### Job Management

- Stop All Jobs: New functionality to terminate all running Celery tasks at once

### Backup and Restore

- Full System Backup: Create ZIP archives containing documents, metadata, conversations, memory, and configurations
- User Data Backup: Lightweight backup scope for documents, folders, and user memory only
- Restore Operations: Support for merge (preserve existing data) and replace (clean restore) modes
- Scheduled Backups: Configure daily or weekly automated backups with retention policies
- Job Tracking: Background Celery tasks with progress monitoring and status updates

### Security Enhancements

- Secure Ticket Auth for SSE: Replace query parameter API keys with short-lived Redis-backed tickets
- Stored XSS Fix: Enforce `Content-Disposition: attachment` for document downloads
- Authentication Middleware Fix: Resolve `UnboundLocalError` edge case

### Chat and Streaming

- SSE Token Buffering: Improved Server-Sent Events streaming with token buffering for smoother word-by-word delivery
- Ollama Support: Fixed pipeline integration and added `429 Too Many Requests` handling with UI warnings

### Graph and Knowledge Management

- Aggressive Graph Maintenance: Integrated cleanup tools into Global Graph Explorer
- Determinism Enforcement: Reproducible results in ingestion and retrieval pipelines
- Orphan Pruning: Remove offline entities and stale communities with recursive cleanup

---

## Improvements and Optimizations

### Performance

- Milvus Search Optimization: Faster vector search and retrieval service integration
- LLM Metrics Aggregation: Aggregate Graph Extraction and Ingestion metrics per document

### Developer Experience

- Utility Scripts: System integrity checks, debugging helpers, and verification tools
- Verify Settings: Added `scripts/verify_llm_settings.py` for ensuring runtime configuration persistence
- Debug Scripts: Orphan chunk detection, relationship verification, community analysis
- Import Linter Integration: Enforce architectural boundaries with `import-linter`
- Architecture Documentation: Onboarding guides, ADR templates, and service boundary docs

### Infrastructure

- Environment Updates: Resource initialization improvements
- Runtime Settings Provider: Centralized configuration wired at startup
- Session Factory Centralization: Unified database session management
- Celery Dispatcher Adapter: Clean background task dispatching

---

## Bug Fixes

- Ingestion Pipeline Stability: Fixed Neo4j client initialization in worker processes
- Tenant Deletion: Safe cascading deletion to Neo4j entities and Milvus vectors
- Context Propagation: Proper tenant context in IngestionService document processing
- Graph Extractor: Correct metric labels in GraphExtractor
- Frontend Stats: Real-time updates for document/folder action statistics
- Backup Reliability: Fixed Neo4j client event loop mismatch in Celery workers preventing concurrent backups
- Vector Backup Fix: Resolved empty vector backups by dynamically detecting active Milvus collection

---

## Breaking Changes

> **Warning**: This release contains significant architectural changes that may require migration steps.

### API Changes

- API routes updated to use clean architecture services
- Some endpoint response structures may have changed

### Database Changes

- New database migration for vector collection management
- New database migration for backup/restore tables (backup_jobs, restore_jobs, backup_schedules)
- Tenant isolation improvements may require data verification

### Configuration Changes

- Settings now loaded via composition root
- Legacy configuration patterns deprecated

---

## Documentation Updates

- Determinism Report: Added reproducibility analysis
- CI Design: Added documentation for Continuous Integration strategy
- API Endpoints: Updated endpoint documentation
- Service Boundaries: Clear domain separation documented
- Pipeline Documentation: Ingestion and processing flows explained

---

## Testing

- Integration Tests: Cost tracking, ingestion pipeline, search integration
- Suite Overhaul: Fixed async/await usage, auth mocking, data seeding, and tenant isolation in integration tests
- Unit Tests: Generation service, LLM steps, session factory, runtime settings
- Security Tests: Tenant isolation verification, chat permissions
- Graph Tests: Security traversal, processor, and extractor coverage

---

## Removed

- Legacy Modules: Deprecated core service modules removed
- Generated Files: Cleaned up repository from build artifacts
- Internal Docs: Untracked internal documentation from version control

---

## Statistics

| Metric        | Count               |
| ------------- | ------------------- |
| Total Commits | 73                  |
| Files Changed | 498                 |
| Insertions    | 26,274              |
| Deletions     | 17,371              |
| New Tests     | 15+ test files      |
| Scripts Added | 10+ utility scripts |
