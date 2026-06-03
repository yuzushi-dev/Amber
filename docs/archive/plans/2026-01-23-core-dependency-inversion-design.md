# Core Dependency Inversion Design

Date: 2026-01-23
Owner: Codex
Scope: Remove all `src.amber_platform` imports from `src/core` without changing pipelines.

## Goal
Eliminate platform imports inside core by introducing minimal ports/providers and wiring them from composition root, preserving runtime behavior and existing pipelines.

## Constraints
- Stay on the current branch.
- Avoid changing pipeline behavior and request/task flows.
- Keep changes lightweight and focused on boundaries.
- Prioritize maintainability, testability, and performance.

## Current State (Key Findings)
- `src/core` still imports `src.amber_platform.composition_root` in multiple modules (graph, generation, ingestion, retrieval, admin ops).
- `src/core/events/dispatcher.py` is already decoupled via publisher port.
- Composition root already uses the canonical session factory from core.

## Proposed Architecture
### 1) Graph Client Provider
- Introduce a core port/provider for graph access (minimal interface: `execute_read`, `execute_write`).
- Add `set_graph_client()` and `get_graph_client()` in core.
- Core modules use `get_graph_client()` instead of importing `platform`.
- Composition root sets the graph client at startup using the platform instance.

### 2) Settings Provider
- Introduce a core settings provider with `set_settings_provider()` and `get_settings()` (and optional `get_settings_lazy()` shim if needed).
- Core modules use the provider instead of importing `get_settings_lazy` from composition root.
- Composition root wires provider from the existing runtime settings.

### 3) Keep Call Signatures Stable
- Avoid changing function signatures used by pipelines.
- Use provider access inside functions to preserve usage.

## Migration Steps (High Level)
1) Add providers and tests (graph + settings).
2) Update core modules to use providers, remove platform imports.
3) Wire providers in composition root startup.
4) Add guardrails (import-linter rule or CI check) to prevent regressions.

## Testing Strategy
- Unit tests for providers:
  - Raises clear error when not configured.
  - Returns injected fake when configured.
- Unit test for a core function using graph provider (e.g., `query_graph`).
- Optional smoke test for existing pipeline endpoints to confirm no behavioral changes.

## Success Metrics / Criteria
- `rg "amber_platform" src/core` returns 0.
- No application layer modules import infrastructure from platform.
- Core functions can be unit-tested with injected fakes without platform imports.
- Existing pipeline tests (or minimal smoke tests) still pass.

## Risks and Mitigations
- Risk: Hidden imports remain. Mitigation: add a boundary check in CI.
- Risk: Provider not configured at runtime. Mitigation: fail fast with explicit error on startup.

## Definition of Done
- All `src/core` modules are free of `amber_platform` imports.
- Providers are wired in composition root.
- Tests added for provider behavior and at least one core usage.
- No pipeline behavior changes observed.
