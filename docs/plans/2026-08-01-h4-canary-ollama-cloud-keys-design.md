# H4 Canary Ollama Cloud Key Propagation Design

## Context

The H4 production canary resolves `DEFAULT_LLM_PROVIDER=ollama_cloud` and
`DEFAULT_LLM_MODEL=gemma4:31b-cloud`, but `deploy/docker-compose.canary.yml`
does not pass `OLLAMA_CLOUD_API_KEYS` to either canary service. The base
Compose file already passes the variable to both the live API and live worker.
As a result, API health, authentication, worker health, SPLADE, and FlashRank
can all pass while the first generated RAG answer fails because the provider
factory receives an empty key list.

## Decision

Mirror the established base-Compose pattern in the canary overlay by adding
exactly one entry to both `api-canary` and `worker-canary`:

```yaml
- OLLAMA_CLOUD_API_KEYS=${OLLAMA_CLOUD_API_KEYS:-}
```

This is deliberately narrower than adding `env_file`, which would expose the
entire production environment to the services and couple the reusable overlay
to one host path. YAML anchors or service inheritance would enlarge the change
surface without improving this one-variable propagation fix.

## Safety and verification

Tests must prove both static uniqueness and resolved propagation. A static YAML
test requires the exact interpolation entry once per canary service. A Compose
resolution test injects a non-secret sentinel and requires the same value in
the resolved API and worker environments. The implementation remains local
until the focused H4 suite and repository gates are green. No production
container, datastore, volume, environment file, remote branch, or pull request
is touched by this work.
