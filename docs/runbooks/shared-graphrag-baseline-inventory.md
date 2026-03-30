# Shared GraphRAG Baseline Inventory

<!-- markdownlint-disable MD013 -->

## Purpose

This document isolates the current Shared GraphRAG rollout file set that is already live in production or required to reproduce the live behavior.

It is an operational inventory, not a replacement for version control.

## Current Constraint

Until this file set is fully committed in git, production reproducibility remains partial.

This inventory exists to make the intended baseline explicit and reviewable.

## Expected Schema Baseline

- Alembic head must include `20260327_1900_fix_document_share_rls_recursion`

## Core Backend Files

- `src/api/config.py`
- `src/api/deps.py`
- `src/api/middleware/auth.py`
- `src/api/routes/admin/__init__.py`
- `src/api/routes/admin/observability.py`
- `src/api/routes/documents.py`
- `src/api/routes/query.py`
- `src/core/admin_ops/application/metrics/collector.py`
- `src/core/admin_ops/application/rules_service.py`
- `src/core/admin_ops/application/tuning_service.py`
- `src/core/generation/application/generation_service.py`
- `src/core/ingestion/application/document_sharing_service.py`
- `src/core/ingestion/application/use_cases_documents.py`
- `src/core/ingestion/domain/document_share.py`
- `src/core/ingestion/domain/ports/document_repository.py`
- `src/core/ingestion/infrastructure/repositories/postgres_document_repository.py`
- `src/core/retrieval/application/retrieval_service.py`
- `src/core/retrieval/application/search/global_search.py`
- `src/core/retrieval/application/search/graph_traversal.py`
- `src/core/retrieval/application/use_cases_query.py`
- `src/core/tenants/application/effective_config.py`
- `src/core/tenants/application/query_scopes.py`

## Provisioning Freeze Files

- `src/api/routes/admin/provisioning.py`
- `src/core/admin_ops/application/provisioning_policy.py`
- `src/core/admin_ops/application/provisioning_service.py`

## Database Migrations

- `alembic/versions/20260327_1600_add_document_shares.py`
- `alembic/versions/20260327_1800_default_owner_manage_document_shares.py`
- `alembic/versions/20260327_1900_fix_document_share_rls_recursion.py`

## Frontend Files

- `frontend/src/features/auth/hooks/useAuth.ts`
- `frontend/src/features/documents/components/UploadWizard.tsx`
- `frontend/src/features/documents/components/DocumentLibrary.tsx`
- `frontend/src/features/documents/components/DocumentShareDialog.tsx`
- `frontend/src/features/documents/components/BulkDocumentShareDialog.tsx`
- `frontend/src/features/documents/pages/DocumentDetailPage.tsx`
- `frontend/src/features/documents/stores/useUploadStore.ts`

## Test Files

- `tests/integration/test_documents_shared_visibility.py`
- `tests/integration/test_document_repository_visibility.py`
- `tests/integration/test_document_share_management.py`
- `tests/integration/test_document_share_metrics.py`
- `tests/integration/test_document_upload_share_targets.py`
- `tests/integration/test_retrieval_service.py`
- `tests/security/test_graph_security.py`
- `tests/unit/test_effective_config.py`
- `tests/unit/test_generation_service.py`
- `tests/unit/test_provisioning_policy.py`
- `tests/unit/test_query_share_metrics.py`
- `tests/unit/test_retrieval_service_hybrid.py`
- `tests/api/test_query_scope_resolution.py`

## Runbooks

- `docs/runbooks/shared-graphrag-migration-runbook.md`
- `docs/runbooks/shared-graphrag-restore-drill.md`
- `docs/runbooks/document-sharing-pilot-checklist.md`
- `docs/runbooks/document-sharing-onboarding.md`
- `docs/runbooks/shared-graphrag-cleanup.md`

## Operator Checks

Before treating the baseline as stable, verify:

1. `git status` clearly identifies this rollout file set
2. `alembic current` matches the schema baseline
3. targeted shared-doc tests are green
4. `amber2-api-1` is healthy after restart

## Exit Condition

This inventory is complete when the listed file set matches the live Shared GraphRAG behavior and is ready to be checkpointed together in version control.
