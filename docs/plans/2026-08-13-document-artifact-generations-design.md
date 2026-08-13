# Document Artifact Generations Design

## Goal

Make document reprocessing lossless: a failed attempt must never remove or hide the last
published vectors, chunks, graph, metadata, or source object.

## Invariants

1. Readers see one published generation per document.
2. Writers only create artifacts in a private staging generation.
3. Publishing is a PostgreSQL pointer change performed with the document READY transition.
4. Failure and retry cleanup target only the staging generation.
5. Garbage collection runs only after publication and may fail without hiding the new generation.
6. Existing rows with no generation remain readable through a `NULL = legacy` fallback.
7. Migrations are additive and never delete, rewrite, or re-embed production data.

## Data model

- `documents.active_generation_id` is nullable. `NULL` means the existing legacy artifacts.
- `documents.pending_generation_id` identifies the content/source awaiting publication.
- `document_generations` records generation id, document/tenant, content hash, storage path,
  filename, status, timestamps, and failure details.
- `chunks.generation_id` is nullable. Existing chunks remain legacy; new chunks belong to a
  generation.
- `processing_attempt_id` protects the state machine from duplicate workers. It is not an
  artifact generation and cannot substitute for one.

## Write and publish flow

Upload/replace stores new bytes under the existing hash-versioned object key and creates a
pending generation without changing the public document content pointer. Processing reads the
pending generation, creates Postgres chunks, Milvus vectors, and Neo4j Chunk/MENTIONS data tagged
with its generation id, and validates all stages. A single PostgreSQL transaction then marks the
generation published, changes `documents.active_generation_id`, copies the generation's public
content fields to the document, and transitions it to READY. Cache invalidation follows commit.

If any stage fails, only that generation is marked failed and its staging artifacts are eligible
for cleanup. The prior `active_generation_id` and document public fields remain unchanged. Cleanup
failure is logged and retried later; it never changes the active pointer.

## Read compatibility

Vector and graph results carry `generation_id`. Retrieval validates candidates against the
document's active generation; legacy documents accept only artifacts with `generation_id IS NULL`.
Postgres chunk lookup uses the same rule. Searches overfetch before validation so stale generations
cannot consume the requested top-k.

Neo4j Chunk identity includes generation. Generation-specific MENTIONS relationships prevent a
staging chunk from becoming visible. Graph traversal accepts only Chunk nodes matching the active
generation map resolved from PostgreSQL. Entity nodes remain tenant-global; their visibility is
derived from active Chunk relationships.

## Migration and rollback

The migration follows the current Alembic head `20260812_1600`, adds nullable columns/table/indexes,
and performs no data update. Downgrade drops only the new empty-generation structures and is allowed
only after proving no non-null generation data exists. Production rollout requires duplicate and
lock preflight plus a verified backup.

## Verification

Integration tests must prove that failures after extraction, embedding, Milvus write, Neo4j write,
graph partial result, or PostgreSQL publish retain the old queryable generation. Success must expose
only the new generation; GC failure must leave it exposed. Legacy `NULL` rows must remain readable.
The prodmirror must exercise failure and success on a mirror-only canary document and compare all
production-derived counts before and after.
