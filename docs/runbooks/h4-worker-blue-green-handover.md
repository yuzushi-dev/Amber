# H4 worker blue/green handover

This runbook replaces the three H3 live Celery workers with three H4 workers,
one replica at a time. It is intentionally manual and fail-closed: every
replica has an isolated probe queue, the old container is retained as the
rollback unit, and the next replica is blocked until the current checkpoint is
green.

The procedure never recreates a datastore, never runs a migration, and never
removes a container or volume. `--no-deps` is mandatory on every Compose
mutation. Stop immediately if a command resolves a different project, source
revision, volume, container, or queue from the recorded preflight.

## Preconditions

1. Work from the immutable production worktree for the reviewed merge commit.
   Record the full commit and require a clean worktree.
2. Resolve the Compose model from all three files and compare its top-level
   volumes with the current base-plus-canary model:
   `docker-compose.yml`, `deploy/docker-compose.canary.yml`, and
   `deploy/docker-compose.worker-h4-live.yml`.
3. Confirm the H4 source/config/alembic and both package mounts are read-only,
   `AMBER_CANARY=true`, the expected `OLLAMA_CLOUD_API_KEYS` variable is
   non-empty without printing it, and the H4 runtime volume is the already
   verified candidate.
4. Record PostgreSQL document, chunk, API-key, and usage counts; record all
   Celery `active`, `reserved`, and `scheduled` tasks; record the live queue
   depths and the complete container/volume inventory.
5. Take a fresh complete online backup without retention cleanup. First run
   `bash scripts/backup.sh --dry-run --destination=/opt/backups/amber --retention=0`.
   After reviewing that plan, run the same command without `--dry-run`, then
   run `bash scripts/verify_backup.sh --backup=<new-backup-directory>`. The
   verification must exit zero. A previously completed non-production restore
   drill must cover the same backup format and application revision.
6. Confirm the current API canary and all three H3 workers are healthy. Run the
   read-only API smoke suite and one known-good RAG query before mutation.
7. Obtain **conferma diretta** from the operator after showing the exact first
   replica command. A prior general approval is not sufficient for the first
   production worker start.

Use a shell array so every invocation has the same project and overlays:

```bash
compose=(docker compose --env-file /root/amber2/.env --project-name amber2 \
  -f docker-compose.yml \
  -f deploy/docker-compose.canary.yml \
  -f deploy/docker-compose.worker-h4-live.yml)
```

Before each real start, preview the exact action:

```bash
"${compose[@]}" --dry-run up -d --no-deps --no-build --pull never worker-h4-live-1
```

The real command differs only by omission of `--dry-run` and is allowed only
after the direct confirmation described above.

## Promote one replica

Perform this section for pair 1, then 2, then 3. Do not overlap pairs. The
example promotes `worker-h4-live-1` and drains `amber2-worker-9`; substitute
only the explicitly recorded pair names and `h4_promotion_N` queue.

### 1. Start and prove H4

```bash
"${compose[@]}" up -d --no-deps --no-build --pull never worker-h4-live-1
docker inspect --format '{{.State.Status}} {{.State.Health.Status}} {{.Config.Image}}' amber2-worker-h4-live-1
```

Confirm from `docker inspect` that the source and package mounts match the
preflight and are read-only. Confirm logs contain no import, provider, startup,
or task errors. Send a task to the replica-private queue from the healthy H4
API canary:

```bash
docker exec amber2-api-canary-1 python - <<'PY'
from src.workers.celery_app import celery_app

result = celery_app.send_task(
    "src.workers.tasks.health_check",
    queue="h4_promotion_1",
)
payload = result.get(timeout=30)
assert payload, payload
print("private H4 probe: PASS")
PY
```

If the private probe fails, do not touch H3. Diagnose H4; if it has no active,
reserved, or scheduled work, stop only this new H4 container with the graceful
command shown in Rollback.

### 2. Stop delivery to exactly one H3 worker

Derive the H3 Celery node from the retained container hostname and verify it
answers before changing its consumers:

```bash
h3_container=amber2-worker-9
h3_node="celery@$(docker inspect --format '{{.Config.Hostname}}' "$h3_container")"
docker exec amber2-worker-h4-live-1 celery -A src.workers.celery_app inspect ping -d "$h3_node" -j
for queue in high_priority celery evaluation low_priority; do
  docker exec amber2-worker-h4-live-1 celery -A src.workers.celery_app \
    control cancel_consumer "$queue" -d "$h3_node" -j
done
```

Every control reply must identify only `$h3_node` and report success. A timeout,
extra destination, or negative reply blocks the handover.

### 3. Prove the H3 worker is drained

Capture all three JSON inspections and require the destination list to be
empty. Repeat until empty; do not impose a short deadline on legitimate work.

```bash
docker exec amber2-worker-h4-live-1 celery -A src.workers.celery_app inspect active -d "$h3_node" -j
docker exec amber2-worker-h4-live-1 celery -A src.workers.celery_app inspect reserved -d "$h3_node" -j
docker exec amber2-worker-h4-live-1 celery -A src.workers.celery_app inspect scheduled -d "$h3_node" -j
```

For each output, parse the JSON and assert that the value for exactly
`$h3_node` is `[]`. Also confirm live queue depths are stable or decreasing and
that the H4 worker has no task failures. If the node disappears before an empty
reply is captured, stop: the drain is unproven.

### 4. Gracefully retain H3 as rollback

Only after all three drain assertions are empty:

```bash
docker stop --time 300 "$h3_container"
```

Confirm the old container is stopped but still present. Re-run PostgreSQL
counts, queue/task inspection, API smoke, and a known-good RAG query. Counts
that can only grow must not decrease; task failures, lost documents, unhealthy
services, or unexplained queue growth block the next pair.

Record the checkpoint before starting pair 2. Repeat with the exact mapping:

| Pair | New service | Private queue | Retained H3 container |
|---|---|---|---|
| 1 | `worker-h4-live-1` | `h4_promotion_1` | `amber2-worker-9` |
| 2 | `worker-h4-live-2` | `h4_promotion_2` | `amber2-worker-10` |
| 3 | `worker-h4-live-3` | `h4_promotion_3` | `amber2-worker-11` |

The mapping is valid only if preflight confirms those are the current live H3
containers. Otherwise stop and rewrite the mapping from observed state.

## Rollback

Rollback is symmetric and one replica at a time. It keeps every datastore and
both worker generations intact.

1. Start the retained H3 container with `docker start <retained-H3-container>`.
2. Wait for its Celery node to answer `inspect ping`. The boot-recovery stale
   threshold must remain at least 30 minutes; a recently drained worker must
   not reset fresh documents.
3. Stop delivery to the paired H4 node with `cancel_consumer` for all four live
   queues.
4. Require `inspect active`, `inspect reserved`, and `inspect scheduled` to
   return empty lists for exactly that H4 node.
5. Retain H4 with a graceful `docker stop --time 300 <H4-container>`.
6. Re-run the data invariants, API smoke, RAG query, queue checks, and error-log
   checks before rolling back another pair.

If data invariants change unexpectedly, freeze the handover: keep all
containers and volumes present, preserve logs and the verified backup, and
escalate as an incident. Do not attempt an in-place restore on production
during diagnosis.

## Completion gate

The handover is complete only when all three H4 workers are healthy, each
private probe passed, the three H3 containers remain stopped and available,
all live queues have consumers, API smoke and RAG query pass, no new worker/API
errors appear during soak, and every recorded data invariant is preserved.
