# Document Sharing Onboarding

<!-- markdownlint-disable MD013 -->

## Purpose

This runbook defines how to onboard a new tenant into the Shared GraphRAG model after the Product Enablement pilot.

The onboarding target is a non-default tenant that should:

- keep its own local documents
- receive selected `default` documents through `document_shares`
- inherit runtime config from `default` unless overridden

## Principles

1. `default` is the canonical owner of shared Carbonio documents.
2. Non-default tenants do not inherit document visibility automatically.
3. Every shared document must be granted through `document_shares`.
4. Cleanup of historical duplicates remains deferred until the end of the migration program.

## Preconditions

Proceed only if:

- the pilot checklist has passed
- the target tenant already exists
- the API is healthy
- share management and ACL-aware retrieval feature flags are enabled
- the operator has a super admin key or is acting as admin in `default`

## Onboarding Workflow

### 1. Confirm tenant metadata

Capture:

- tenant ID
- tenant display name
- target business owner
- admin contacts

### 2. Confirm inherited config baseline

Review the target tenant config and confirm whether it should:

- inherit all prompts and runtime tuning from `default`
- override any specific field

If no override is needed, leave the tenant config sparse and rely on effective config resolution.

### 3. Decide which `default` documents to share

The onboarding owner must define one of:

- a curated document list
- a folder or content grouping mapped to specific document IDs
- a phased rollout list

Do not assume that all `default` documents should be visible.

### 4. Apply shares

Use one of:

- upload-time share selection for new `default` documents
- post-upload share management for one document
- bulk share workflow for existing `default` documents

After the operation, confirm that the intended `document_shares` rows exist.

### 5. Validate tenant visibility

With a tenant-scoped key, confirm:

- local documents are still visible
- intended shared `default` documents are visible
- unrelated `default` documents remain hidden

### 6. Validate retrieval

Run one `basic` and one `global` query that should cite a shared document.

Then run one negative test against a non-shared `default` document and confirm it is not returned.

### 7. Record onboarding outcome

Record:

- tenant ID
- operator
- date
- share target set used
- validation document IDs
- any overrides applied to config

## Suggested Smoke Commands

### List visible docs

```bash
curl -s 'http://localhost:8000/v1/documents?limit=200' \
  -H 'Authorization: Bearer <tenant-key>' \
  -H 'X-Tenant-ID: <tenant-id>'
```

### Query basic

```bash
curl -s http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <tenant-key>' \
  -H 'X-Tenant-ID: <tenant-id>' \
  -d '{"query":"What does the shared Carbonio corpus say about mailbox administration?","mode":"basic"}'
```

### Query global

```bash
curl -s http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <tenant-key>' \
  -H 'X-Tenant-ID: <tenant-id>' \
  -d '{"query":"Summarize the shared Carbonio guidance relevant to this tenant","mode":"global"}'
```

### Observability summary

```bash
curl -s 'http://localhost:8000/v1/admin/observability/document-shares/summary' \
  -H 'Authorization: Bearer <super-admin-key>'
```

## Rollback Guidance

If onboarding fails for a tenant:

1. remove or replace only the intended `document_shares` rows for that tenant
2. keep the canonical `default` documents untouched
3. keep local tenant documents untouched
4. avoid emergency duplication of shared corpus into the tenant

Use rollback to restore visibility behavior, not to rewrite historical data.

## What To Avoid

- do not clone the whole `default` corpus into the tenant
- do not use cleanup of historical duplicate vectors as an onboarding shortcut
- do not assume `query_scopes` alone is enough to authorize retrieval
- do not grant one non-default tenant access to another non-default tenant's local documents
