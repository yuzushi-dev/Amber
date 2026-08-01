# H4 canary shared-mount isolation

## Context

The production Compose dry-run for the exact H4 candidate showed that the canary API and worker would mount three existing production paths read-write: uploads, the active H3 package volume, and the shared Hugging Face cache. The H4 candidate volume and source tree are already read-only.

Starting that canary would therefore exceed the zero-impact production authorization even though the canary entrypoint skips migrations and its worker consumes dedicated queues.

## Decision

Keep the canary connected to the live backing services for read-only smoke queries, but make every filesystem path shared with the live stack read-only in both canary services:

- `graphrag-uploads:/app/uploads:ro`
- `pip-packages:/app/.packages:ro`
- `./.cache/huggingface:/home/appuser/.cache/huggingface:ro`
- retain `h4-ml-runtime:/app/.packages-h4:ro`

This is a Compose-only hardening change. It does not change the live Compose file, volume contents, service state, database state, or queue routing.

## Safety properties

- The API and worker can import the existing H3 fallback packages but cannot alter them.
- Preloaded H4 packages and model caches remain immutable.
- The canary cannot write uploaded files or mutate the shared Hugging Face cache.
- Any unexpected write attempt fails closed instead of changing production state.
- No datastore write protection is implied by these mount flags; canary validation must continue to use the existing read-only smoke path and dedicated worker queues.

## Verification

A repository contract test requires both canary services to use all four shared mounts read-only and rejects the former read-write declarations. The full repository verification suite must pass before the change is proposed for merge. After merge, production Compose must be rendered from the exact merge SHA and inspected before any canary start.
