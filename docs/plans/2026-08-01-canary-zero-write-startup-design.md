# Canary zero-write startup and stable Compose identity

## Incident

An API-only production canary launched from an exact-SHA worktree exposed two independent unsafe defaults:

1. Compose derived its project name from the worktree directory and eagerly created six empty datastore volumes even with `up --no-deps`.
2. The API lifespan always called `ensure_bootstrap_key`. Because the canary overlay did not supply `DEV_API_KEY`, startup used the known development fallback and inserted an active admin/root API key into production.

The canary was stopped without queries. The inserted row was backed up and disabled without deletion. The empty volumes remain untouched pending explicit disposal approval.

## Options

- Pass the production development key and add `--project-name amber2` only to the operator command. This avoids the observed insert in the current state but still permits bootstrap writes when tenant linkage is missing, and remains vulnerable to command drift.
- Give the canary a separate read-only database role. This is the strongest database boundary but requires credential, role, RLS, and connection-string rollout beyond the immediate incident scope.
- Make canary startup explicitly skip API-key bootstrap and fix the overlay project identity to `amber2`, while documenting the explicit project flag. This directly closes both root causes with a small, testable patch.

The third option is selected. A dedicated read-only database role remains a future defense-in-depth improvement.

## Design

`src/api/main.py` exposes a small `_bootstrap_api_key_if_allowed` helper. When `AMBER_CANARY=true`, it returns without constructing `ApiKeyService` or invoking `ensure_bootstrap_key`. Normal API startup retains existing behavior. Compatibility and integrity checks remain read-only and continue to execute.

`deploy/docker-compose.canary.yml` declares top-level `name: amber2`, so Compose resolves the shared production datastore volume names even when invoked from an exact-SHA worktree. Usage and rollback examples also pass `--project-name amber2` as visible defense in depth.

## Verification

- Unit test proves canary mode never constructs or calls the API-key service.
- Security contract proves the overlay project name is exactly `amber2` and every documented canary Compose command includes the explicit project flag.
- RED is observed on merge SHA `c348a963`; focused, complete, resolved-Compose, and full repository gates must pass before PR.
- No further production canary is allowed until merge, exact-SHA staging, empty-volume disposition, and a new explicit GO.
