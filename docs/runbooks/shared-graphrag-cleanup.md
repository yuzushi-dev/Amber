# Shared GraphRAG Cleanup Plan

<!-- markdownlint-disable MD013 -->

## Purpose

This document defines the deferred cleanup strategy for historical duplicate data after Shared GraphRAG document sharing is stable in production.

This is a planning document only. It does not authorize immediate deletion of any PostgreSQL rows, Milvus vectors, Neo4j nodes, or object storage blobs.

## Current Intent

Cleanup stays at the end of the program, after:

- pilot validation is signed off
- at least one onboarding wave beyond Product Enablement is complete, or operators explicitly decide the current tenant footprint is stable enough
- ACL-aware vector and graph retrieval have been stable in production for a defined observation window

## Cleanup Goals

1. remove redundant tenant-local copies of documents that are now served canonically from `default`
2. remove redundant vectors that exist only because of earlier duplication workarounds
3. preserve all tenant-local documents that are genuinely tenant-specific
4. keep the cleanup reversible at every batch boundary

## Preconditions

Do not start cleanup until all are true:

- Shared GraphRAG read path is stable
- onboarding runbook has been used successfully
- infrastructure-level backup and restore drill have passed
- a duplicate inventory report exists for Postgres and Milvus
- rollback owner is assigned
- the exact cleanup batch is approved

## Required Inventory

Before any deletion proposal, export:

- `documents` grouped by tenant
- `chunks` grouped by tenant
- `document_shares` grouped by target tenant
- duplicate candidates by `content_hash`
- duplicate candidates by filename
- Milvus entity counts per collection
- representative graph stats for shared documents

## Recommended Cleanup Strategy

### Phase 1. Mark duplicate candidates

Produce a report of non-default documents that appear to be duplicates of `default` documents.

A candidate match should prefer:

1. `content_hash`
2. stable canonical metadata
3. filename only as a last resort

Do not delete anything in this phase.

### Phase 2. Validate shadowing behavior

For each batch candidate, confirm that the tenant already has equivalent visibility through:

- a canonical `default` document
- an active `document_shares` row to the target tenant
- working vector retrieval
- working graph retrieval

If any of those are false, the candidate is not ready for cleanup.

### Phase 3. Archive batch manifest

Before any delete operation, store a manifest containing:

- tenant ID
- duplicate local document IDs
- canonical `default` document IDs
- related chunk counts
- expected Milvus collection impacts
- operator and approval timestamp

### Phase 4. Remove vectors first, then relational duplicates

If cleanup is approved:

1. remove the duplicate vectors for the tenant batch
2. verify retrieval still cites the canonical shared document
3. remove duplicate relational rows for the same batch
4. verify the document list, detail, and query paths again

Do not clean all tenants or all duplicates in one operation.

### Phase 5. Re-measure and pause

After each batch:

- recapture counts
- compare to the manifest
- stop if any mismatch or retrieval regression appears

## Rollback Expectations

Rollback must be possible per batch, not only globally.

The rollback package for a batch should include:

- manifest of deleted document IDs
- export of deleted rows
- vector identifiers or collection-level restore instructions
- smoke-check commands and expected outputs

## Explicit Guardrails

- never start cleanup from filename matches alone when `content_hash` disagrees
- never delete tenant-local documents that do not have a canonical shared replacement
- never combine cleanup with unrelated schema changes
- never run cleanup during the same window as a first-time tenant onboarding
- never use cleanup as the first response to an ACL bug

## Suggested Exit Criteria

Cleanup can be considered complete only when:

- shared corpus is served canonically from `default`
- non-default tenants retain only tenant-specific local data plus intended overlays
- duplicate vectors introduced by prior workarounds are removed
- retrieval parity remains acceptable after each cleanup batch

Until then, historical duplicates are an accepted cost of a safer migration.
