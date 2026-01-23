# Architecture Remediation Design

## Goal
Remove the confirmed architectural violations while preserving existing pipelines and behavior. The remediation focuses on dependency inversion, infrastructure leakage, transaction boundaries, and session factory consolidation for a Clean Architecture/DDD-aligned backend.

## Scope
- Backend only (core, infrastructure, API wiring, workers).
- No functional changes to ingestion, retrieval, generation, or admin pipelines.
- Structural changes only: dependency direction, composition root wiring, and consistent transaction/session handling.

## Key Decisions
- Introduce a shared runtime settings provider in `src/shared/kernel` so core and infrastructure can read settings without importing the composition root.
- Make `src/core/database/session.py` the single canonical session factory and route all session creation through it.
- Enforce ports in application services (use cases and services) so no application layer imports infrastructure implementations.
- Keep composition root as the wiring layer only (client lifecycle + builders). Core must not import it.
- Replace synchronous Redis calls in core event dispatcher with an async adapter injected via a port.

## Component Changes
1. **Settings provider**
   - New `src/shared/kernel/runtime.py` with `configure_settings()` and `get_settings()`.
   - API and worker startup call `configure_settings(settings)`.
   - Core modules use `get_settings()` instead of `get_settings_lazy()`.

2. **Session factory consolidation**
   - `src/core/database/session.py` is canonical.
   - `src/amber_platform/composition_root.py` uses `configure_database()` and `get_session_maker()` instead of creating a new engine.
   - `src/api/deps.py` uses the canonical session maker.

3. **Ports and dependency inversion**
   - Application use cases accept ports for repositories, storage, graph, vector store, and task dispatchers.
   - Composition root builds these concrete dependencies and injects them.
   - Singletons like `context_graph_writer` and `graph_enricher` are built in composition root and passed in.

4. **Event publishing**
   - Add `StateChangePublisher` port.
   - Implement `RedisStatePublisher` adapter with async client.
   - `EventDispatcher` delegates to the port so core stays infrastructure-free.

5. **Route wiring**
   - Routes call composition root builders instead of instantiating concrete clients (e.g., Milvus) directly.

6. **Architecture guardrails**
   - Add import-linter rule forbidding `src.core` -> `src.amber_platform`.
   - Tighten existing app-layer contracts to block infra imports.

## Data Flow Impact
No pipeline behavior changes. Only wiring and dependency direction change. Data flow through ingestion -> embedding -> graph -> ready remains identical.

## Error Handling
No new error pathways. Existing exceptions remain. Any new adapter failures will surface via existing logs and raised exceptions.

## Testing Strategy
- Run `poetry run lint-imports` to confirm architectural boundaries.
- Re-run ingestion and retrieval integration tests for parity.
- Validate key API endpoints (upload, retrieve, query) if integration tests are unavailable.

