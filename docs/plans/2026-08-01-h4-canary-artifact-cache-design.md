# H4 canary artifact-owned cache

## Context

The exact-SHA production worktree does not contain the ignored path `./.cache/huggingface`. The canary Compose overlay bind-mounts that path read-only into both services, while the worker sets `HF_HOME` to the mount. Starting the canary would make Docker create a root-owned empty host directory and would route default Hugging Face lookups away from the validated H4 artifact cache.

The H4 candidate already contains the preloaded, offline-validated cache at `/app/.packages-h4/hf-cache`, and the H4 volume is mounted read-only by both canary services.

## Options considered

1. Create and populate a cache in every exact-SHA worktree. This duplicates model data, introduces ownership drift, and weakens the single validated-artifact boundary.
2. Mount an H4 volume subpath at the default Hugging Face location. This adds Compose/engine-version dependence and a second mount of the same volume.
3. Remove the host bind and point Hugging Face environment variables at the cache inside the existing H4 mount. This is deterministic, minimal, and reuses the validated immutable artifact.

Option 3 is selected.

## Design

Both `api-canary` and `worker-canary` set:

- `HF_HOME=/app/.packages-h4/hf-cache`
- `HUGGINGFACE_HUB_CACHE=/app/.packages-h4/hf-cache/hub`

The `./.cache/huggingface` bind is removed from both services. Uploads, active H3 packages, and the H4 artifact remain read-only. No live Compose service changes, datastore migrations, queue changes, or volume writes are introduced.

## Safety and verification

A security contract parses the Compose overlay per service and requires both cache environment variables, the read-only H4 mount, and absence of any worktree Hugging Face bind. The contract must fail on merge SHA `76ee7540` before the patch and pass afterward. The resolved Compose config must show no host cache mount and both variables pointing inside the H4 volume. Full repository verification and remote CI are required before merge.
