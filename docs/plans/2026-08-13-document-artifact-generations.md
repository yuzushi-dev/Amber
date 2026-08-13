# Document Artifact Generations Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Publish document artifacts by generation so failed reprocessing preserves the last known-good production data.

**Architecture:** Build Postgres chunks, Milvus vectors, and Neo4j graph data under a staging generation. Publish by changing the document's active-generation pointer only after every stage succeeds; clean only staging artifacts on failure and old artifacts after publication.

**Tech Stack:** Python 3.11, SQLAlchemy/PostgreSQL, Alembic, Milvus/PyMilvus, Neo4j/Cypher, pytest.

---

### Task 1: Additive generation schema

**Files:**
- Modify: `src/core/ingestion/domain/document.py`
- Modify: `src/core/ingestion/domain/chunk.py`
- Create: `alembic/versions/20260813_1700_add_document_artifact_generations.py`
- Test: `tests/unit/test_document_generation_migration.py`

1. Write a failing migration-shape test for nullable generation fields, indexes, current down revision, and a guarded downgrade.
2. Run the test and verify the missing migration failure.
3. Add the smallest model and migration implementation; perform no backfill.
4. Run the test and the Alembic graph check.
5. Commit only these files.

### Task 2: Generation-aware repository contract

**Files:**
- Modify: `src/core/ingestion/domain/ports/document_repository.py`
- Modify: `src/core/ingestion/infrastructure/repositories/postgres_document_repository.py`
- Test: `tests/unit/test_document_generation_repository.py`

1. Write failing tests for active/legacy chunk visibility and atomic publish compare-and-set.
2. Add repository methods to create/fail/publish generations and validate chunk ids against active generations.
3. Keep `NULL/NULL` as the legacy visibility rule.
4. Run repository tests and commit.

### Task 3: Stage and filter Milvus artifacts

**Files:**
- Modify: `src/core/retrieval/domain/ports/vector_store_port.py`
- Modify: `src/core/retrieval/infrastructure/vector_store/milvus.py`
- Modify: `src/core/retrieval/application/search/vector.py`
- Modify: `src/core/retrieval/application/retrieval_service.py`
- Test: `tests/unit/test_milvus_document_generations.py`
- Test: `tests/unit/test_retrieval_document_generations.py`

1. Write failing tests that require `generation_id` on writes, escaped generation-scoped deletion, and stale-result rejection.
2. Add the dynamic generation field and `delete_by_generation`; remove document-wide cleanup from reprocessing.
3. Overfetch and validate vector candidates against the repository active-generation map.
4. Prove legacy results remain visible and commit.

### Task 4: Stage and filter Neo4j artifacts

**Files:**
- Modify: `src/core/graph/application/writer.py`
- Modify: `src/core/graph/application/processor.py`
- Modify: `src/core/retrieval/application/search/graph_traversal.py`
- Modify: `src/core/graph/infrastructure/neo4j_client.py`
- Test: `tests/unit/test_graph_document_generations.py`

1. Write failing query-shape tests for generation-scoped Chunk identity, visibility, and cleanup.
2. Thread generation id through processor/writer and tag Chunk/MENTIONS data.
3. Filter retrieval by the active-generation map; preserve legacy `NULL` behavior.
4. Add generation-scoped cleanup and commit.

### Task 5: Lossless ingestion, replace, and retry

**Files:**
- Modify: `src/core/ingestion/application/ingestion_service.py`
- Modify: `src/core/ingestion/application/use_cases_documents.py`
- Modify: `src/core/state/machine.py`
- Modify: `src/workers/tasks.py`
- Test: `tests/unit/test_ingestion_generation_publish.py`
- Test: `tests/unit/test_ingestion_generation_failures.py`

1. Write RED tests for an existing READY/legacy generation failing at every boundary while the active data remains unchanged.
2. Create a staging generation at attempt start and remove document-scoped pre-delete/failure cleanup.
3. Publish only after vector and graph success; failure marks and cleans only staging.
4. Change replace to stage content without changing public document fields.
5. Add attempt ownership CAS from #123 where needed for duplicate workers.
6. Run focused tests and commit.

### Task 6: Preserve generation metadata in lifecycle operations

**Files:**
- Modify: backup/export/restore services discovered by `rg "chunks|storage_path|content_hash" src/core/admin_ops src/api`
- Test: focused backup/export/restore tests.

1. Write failing round-trip tests for active and pending generation metadata.
2. Extend existing formats without introducing a second format or new dependency.
3. Run tests and commit.

### Task 7: Integrate safe parts of PRs #121-#123

**Files:** only files required by the selected changes.

1. Port Mistral fail-closed, exact embedding cardinality, graph partial result, retry dispatch, attempt CAS, and community build/swap one behavior at a time.
2. For each behavior, add/port its test first and verify RED on current main.
3. Do not port document-wide pre-delete or failure cleanup.
4. Run focused tests and commit in coherent groups.

### Task 8: Verification and mirror rehearsal

1. Run `make verify-backend`, frontend checks if touched, `git diff --check`, migration graph, and secret scan.
2. Apply migrations to the local prodmirror after snapshot and count preflight.
3. On a mirror-only document, prove failure retains the active generation and success switches it.
4. Compare Postgres/Milvus/Neo4j/object-store counts and query results.
5. Request Terra review, fix blockers with TDD, push a new PR, and close #121-#123 only after the replacement PR is demonstrably complete.
