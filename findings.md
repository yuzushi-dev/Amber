# Findings & Decisions
<!-- 
  WHAT: Your knowledge base for the task. Stores everything you discover and decide.
  WHY: Context windows are limited. This file is your "external memory" - persistent and unlimited.
  WHEN: Update after ANY discovery, especially after 2 view/browser/search operations (2-Action Rule).
-->

## Requirements
<!-- 
  WHAT: What the user asked for, broken down into specific requirements.
  WHY: Keeps requirements visible so you don't forget what you're building.
  WHEN: Fill this in during Phase 1 (Requirements & Discovery).
  EXAMPLE:
    - Command-line interface
    - Add tasks
    - List all tasks
    - Delete tasks
    - Python implementation
-->
<!-- Captured from user request -->
- Remove `src.amber_platform` imports from `src/core` (Clean Architecture boundary fix).
- Keep current pipelines unchanged; stay on current branch; minimize risk.
- Prefer lightweight changes; prioritize maintainability/testability/performance.

## Research Findings
<!-- 
  WHAT: Key discoveries from web searches, documentation reading, or exploration.
  WHY: Multimodal content (images, browser results) doesn't persist. Write it down immediately.
  WHEN: After EVERY 2 view/browser/search operations, update this section (2-Action Rule).
  EXAMPLE:
    - Python's argparse module supports subcommands for clean CLI design
    - JSON module handles file persistence easily
    - Standard pattern: python script.py <command> [args]
-->
<!-- Key discoveries during exploration -->
- `rg "amber_platform" src/core` shows remaining imports in:
  - `src/core/tools/graph.py`
  - `src/core/generation/application/generation_service.py`
  - `src/core/generation/application/intelligence/classifier.py`
  - `src/core/generation/application/intelligence/document_summarizer.py`
  - `src/core/graph/application/context_writer.py`
  - `src/core/graph/application/deduplication.py`
  - `src/core/graph/application/enrichment.py`
  - `src/core/graph/application/setup.py`
  - `src/core/graph/application/writer.py`
  - `src/core/graph/infrastructure/neo4j_client.py`
  - `src/core/ingestion/infrastructure/storage/storage_client.py`
- `src/core/ingestion/infrastructure/extraction/graph_extractor.py`
- `src/core/retrieval/application/query/structured_query.py`
- `src/core/admin_ops/application/evaluation/ragas_service.py`
- Graph app modules like `src/core/graph/application/context_writer.py` and `src/core/graph/application/deduplication.py` call `platform.neo4j_client` directly.
- Generation intelligence modules (classifier, document_summarizer) pull settings via `get_settings_lazy` from composition root.
- Infrastructure clients `Neo4jClient` and `MinIOClient` fall back to `get_settings_lazy` when args are missing.
- `StructuredQuery` uses `platform.neo4j_client` for direct Cypher access.
- `GraphEnricher` uses `platform.neo4j_client` and lazily pulls settings from composition root when creating Milvus store.
- `generation_service` uses `get_settings_lazy` to build an ad-hoc async engine for document title lookup.
- Graph setup script uses `platform.neo4j_client` directly.
- `rg` confirms remaining `amber_platform` imports in graph and generation application modules only.
- Graph extractor and ragas evaluation services also use `get_settings_lazy` in core.
- Graph writer uses `platform.neo4j_client` directly.
- Boundary test lists 11 offenders in core (graph app modules, structured_query, generation, admin ops, graph_extractor).
- Deduplication service uses platform for both execute_read and execute_write.
- Async tests use `pytest.mark.asyncio` in `tests/unit/test_structured_query.py` and others.
- Structured query unit tests import `src.core.query.structured_query` and patch `neo4j_client` (path likely outdated vs current module location).
- `SettingsProtocol` already defines db/minio fields; shared kernel runtime provides `configure_settings` and `get_settings`.
- Worker init configures settings and providers, but does not call `platform.initialize()`; graph provider wiring must account for worker startup.
- `src/core/graph/infrastructure/neo4j_client.py` and `src/core/ingestion/infrastructure/storage/storage_client.py` are currently untracked files in this branch; staging adds full files.
- Task 3 staging shows large insertions because many core modules in the new structure are untracked; committing would add entire files beyond targeted import edits.
- `rg "amber_platform" src/core` now returns no matches after refactor.
- `src/core/events/dispatcher.py` uses publisher port; redis adapter is async (`src/infrastructure/adapters/redis_state_publisher.py`).
- Composition root already uses core session factory (`src/amber_platform/composition_root.py:256-323`).
- Shared kernel runtime already exposes `configure_settings()` and `get_settings()` (`src/shared/kernel/runtime.py`).
- API startup calls `configure_settings()` from shared runtime before platform initialization (`src/api/main.py`).

## Technical Decisions
<!-- 
  WHAT: Architecture and implementation choices you've made, with reasoning.
  WHY: You'll forget why you chose a technology or approach. This table preserves that knowledge.
  WHEN: Update whenever you make a significant technical choice.
  EXAMPLE:
    | Use JSON for storage | Simple, human-readable, built-in Python support |
    | argparse with subcommands | Clean CLI: python todo.py add "task" |
-->
<!-- Decisions made with rationale -->
| Decision | Rationale |
|----------|-----------|
| Introduce graph/settings providers in core | Remove platform imports while preserving call signatures |
| Wire providers from composition root startup | Keep pipelines unchanged and make dependencies explicit |
| Add targeted tests for providers | TDD compliance with minimal test surface |

## Issues Encountered
<!-- 
  WHAT: Problems you ran into and how you solved them.
  WHY: Similar to errors in task_plan.md, but focused on broader issues (not just code errors).
  WHEN: Document when you encounter blockers or unexpected challenges.
  EXAMPLE:
    | Empty file causes JSONDecodeError | Added explicit empty file check before json.load() |
-->
<!-- Errors and how they were resolved -->
| Issue | Resolution |
|-------|------------|
| Dirty worktree with many unrelated changes | Stage only targeted files/hunks |
| Committed extra staged files unintentionally | Record commit and proceed; verify staging before next commit |

## Resources
<!-- 
  WHAT: URLs, file paths, API references, documentation links you've found useful.
  WHY: Easy reference for later. Don't lose important links in context.
  WHEN: Add as you discover useful resources.
  EXAMPLE:
    - Python argparse docs: https://docs.python.org/3/library/argparse.html
    - Project structure: src/main.py, src/utils.py
-->
<!-- URLs, file paths, API references -->
- `src/core/tools/graph.py`
- `src/core/graph/application/*`
- `src/core/generation/application/intelligence/*`
- `src/core/retrieval/application/query/structured_query.py`
- `src/core/admin_ops/application/evaluation/ragas_service.py`

## Visual/Browser Findings
<!-- 
  WHAT: Information you learned from viewing images, PDFs, or browser results.
  WHY: CRITICAL - Visual/multimodal content doesn't persist in context. Must be captured as text.
  WHEN: IMMEDIATELY after viewing images or browser results. Don't wait!
  EXAMPLE:
    - Screenshot shows login form has email and password fields
    - Browser shows API returns JSON with "status" and "data" keys
-->
<!-- CRITICAL: Update after every 2 view/browser operations -->
<!-- Multimodal content must be captured as text immediately -->
-

---
<!-- 
  REMINDER: The 2-Action Rule
  After every 2 view/browser/search operations, you MUST update this file.
  This prevents visual information from being lost when context resets.
-->
*Update this file after every 2 view/browser/search operations*
*This prevents visual information from being lost*
