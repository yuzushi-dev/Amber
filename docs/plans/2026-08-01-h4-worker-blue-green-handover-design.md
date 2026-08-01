# H4 Worker Blue/Green Handover Design

## Goal

Move production Celery consumption from the three preserved H3 workers to
three H4 workers without dropping queued work, killing an active task, or
removing any rollback container or volume.

## Constraints

- Production data loss is a severity-one incident.
- Never use `down`, `rm`, `prune`, volume deletion, or datastore lifecycle
  commands.
- Keep at least one proven consumer on every live queue throughout handover.
- Never stop an H3 worker until its Celery node reports no active, reserved, or
  scheduled tasks after its consumers have been cancelled.
- Keep all H3 containers stopped but preserved for rollback.
- Keep datastore, uploads, H3 runtime, and H4 runtime mounts read-only in the
  H4 workers.
- Every production mutation remains a human-confirmed checkpoint; no script
  automates the whole handover.

## Approaches considered

### Selected: explicit blue/green worker services

Add a small Compose overlay with three stable services:
`worker-h4-live-1`, `worker-h4-live-2`, and `worker-h4-live-3`. Each extends the
already production-proven `worker-canary` configuration, overrides only its
container name, command, restart policy, and graceful-stop window, and listens
to the live queues plus a unique private probe queue.

This supports a one-for-one transition: start and probe H4-1, cancel consumers
on one H3 node, wait for it to drain, preserve-stop it, then repeat. A unique
probe queue proves that the intended H4 replica executed the health task rather
than another live worker.

### Rejected: rolling recreation of the existing worker service

Compose would replace all three H3 replicas under one service. A task could be
killed after the 300-second grace period and redelivered under
`task_acks_late`, risking duplicate destructive pre-ingest cleanup.

### Rejected: ad-hoc one-off containers

`docker compose run` could create H4 consumers, but the resulting production
topology would not be declarative or restart-safe.

## Compose architecture

The new `deploy/docker-compose.worker-h4-live.yml` is used together with the
base and canary files. Each H4 live service:

- extends `worker-canary` from `docker-compose.canary.yml`;
- has a stable, unique container name;
- listens to `high_priority`, `celery`, `evaluation`, `low_priority`, and one
  private queue named `h4_promotion_<n>`;
- sets an explicit Celery hostname and concurrency;
- uses `restart: unless-stopped` and `stop_grace_period: 300s`;
- inherits `AMBER_CANARY=true`, which only suppresses boot recovery in worker
  code and avoids touching documents while H3 and H4 coexist;
- inherits the H4 runtime and all shared mounts read-only.

Periodic recovery remains available after promotion because Celery Beat sends
the periodic recovery task to the default `celery` queue, which H4 consumes.

## Handover data flow

For replica N:

1. Resolve Compose with production env and assert exact source SHA, volumes,
   read-only mounts, queue command, key propagation, and memory limit.
2. Dry-run and start only `worker-h4-live-N` with `--no-deps --no-build
   --pull never`.
3. Wait for Celery ready and the canary recovery-skip log.
4. Send `src.workers.tasks.health_check` only to `h4_promotion_N`; require a
   healthy result and queue depth back to zero.
5. Cancel the four live consumers on exactly one H3 Celery destination.
6. Wait until that destination reports active, reserved, and scheduled all
   empty. If the proof does not converge, stop the handover and leave it
   running.
7. Stop that H3 container with its 300-second grace period; never remove it.
8. Recheck queues, corpus fingerprints, health, restart/OOM, and volume count.

At all times, the other H3 replicas and the newly validated H4 replica continue
consuming live work.

## Failure and rollback

Any failed probe, non-empty drain proof, restart/OOM, new volume, datastore
restart, fingerprint drift, or unexpected log error is a NO-GO. Do not advance
to the next replica.

Rollback is symmetric: start a preserved H3 container, verify it is ready and
consuming the live queues, cancel live consumers on one H4 destination, wait
for active/reserved/scheduled zero, then stop (but do not remove) that H4
container. Repeat one at a time.

## Verification

Automated tests must prove:

- exactly three stable H4 live services exist;
- every command has the four live queues and only its own private probe queue;
- all services inherit `worker-canary`, retain `AMBER_CANARY=true`, receive the
  Ollama Cloud sentinel, and resolve H3/H4/uploads mounts read-only;
- stable names, restart policy, 300-second grace, 2G memory ceiling, and
  project/volume names are correct;
- the overlay never changes datastore services or declares new volumes.

Production proof is separate from unit tests and must be recorded at every
replica checkpoint.
