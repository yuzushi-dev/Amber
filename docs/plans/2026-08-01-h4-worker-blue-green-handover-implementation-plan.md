# H4 Worker Blue/Green Handover Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a declarative, test-guarded H4 worker topology that supports a one-replica-at-a-time production handover without dropping or duplicating Celery work.

**Architecture:** A new Compose overlay declares three stable H4 live workers that extend the proven canary worker configuration. Each consumes the four live queues and a unique private probe queue; production retirement of H3 remains a manual, human-confirmed runbook with fail-closed drain proofs.

**Tech Stack:** Docker Compose, Celery, Redis, pytest, PyYAML, Python subprocess-based Compose validation.

---

### Task 1: Specify the static H4 live worker contract

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`
- Create: `deploy/docker-compose.worker-h4-live.yml`

**Step 1: Write the failing test**

Add a test that loads `deploy/docker-compose.worker-h4-live.yml` and requires
the exact service set `worker-h4-live-1..3`. For each service require:

- `extends.service == "worker-canary"` and
  `extends.file == "docker-compose.canary.yml"`;
- container name `amber2-worker-h4-live-<n>`;
- command includes exactly the live queues plus `h4_promotion_<n>`;
- explicit hostname `h4-live-<n>@%h` and configured concurrency;
- `restart == "unless-stopped"`;
- `stop_grace_period == "300s"`.

Run:

```bash
/home/daniele/Amber/.venv/bin/pytest -q \
  tests/security/test_h4_ml_runtime_artifact.py::test_h4_live_worker_overlay_declares_safe_blue_green_replicas
```

Expected: FAIL because the overlay does not exist.

**Step 2: Implement the minimal overlay**

Create three explicit services, each extending `worker-canary` and overriding
only the stable name, queue command, restart policy, and grace period. Do not
declare volumes, networks, datastore services, or lifecycle hooks.

**Step 3: Run the test**

Expected: PASS.

**Step 4: Commit**

```bash
git add deploy/docker-compose.worker-h4-live.yml \
  tests/security/test_h4_ml_runtime_artifact.py
git commit -m "feat(deploy): add H4 blue-green worker overlay"
```

### Task 2: Specify resolved Compose safety

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`

**Step 1: Write the failing test**

Resolve base + canary + H4-live overlays with sentinel volume names and a
sentinel `OLLAMA_CLOUD_API_KEYS`. Require for every H4 live worker:

- sentinel keys are propagated;
- `AMBER_CANARY == "true"`;
- provider/model are `ollama_cloud`/`gemma4:31b-cloud`;
- `/app/src`, `/app/config`, `/app/alembic`, `/app/uploads`, `/app/.packages`,
  and `/app/.packages-h4` are all read-only;
- H3 and H4 source volumes resolve to the provided sentinels;
- memory limit resolves to 2 GiB;
- the six datastore volume names remain the production names;
- no volume beyond the base/canary set is introduced.

Run only the new test. Expected: FAIL until any merge/extends issue is fixed.

**Step 2: Adjust only the overlay as needed**

Keep changes minimal; do not weaken assertions or duplicate the full worker
environment.

**Step 3: Run the test and the H4/canary suite**

```bash
/home/daniele/Amber/.venv/bin/pytest -q \
  tests/security/test_h4_ml_runtime_artifact.py \
  tests/unit/test_canary_startup_safety.py \
  tests/unit/test_h4_runtime_binding.py
```

Expected: all pass.

**Step 4: Commit**

```bash
git add deploy/docker-compose.worker-h4-live.yml \
  tests/security/test_h4_ml_runtime_artifact.py
git commit -m "test(deploy): prove H4 live worker Compose safety"
```

### Task 3: Add the manual production handover runbook

**Files:**
- Create: `docs/runbooks/h4-worker-blue-green-handover.md`
- Test: `tests/security/test_h4_ml_runtime_artifact.py`

**Step 1: Write the failing documentation contract test**

Require the runbook to contain:

- exact dry-run/start commands with all three Compose files and
  `--no-deps --no-build --pull never`;
- private health-probe commands;
- per-destination `cancel_consumer` instructions;
- active/reserved/scheduled zero gates;
- `docker stop --time 300` but no `docker rm`, `compose down`, prune, or volume
  deletion;
- per-replica invariant checks and symmetric rollback;
- an explicit direct-human-confirmation checkpoint before every production
  mutation.

Expected: FAIL because the runbook does not exist.

**Step 2: Write the minimal runbook**

Document discovery of actual H3 Celery destinations rather than hardcoding
container IDs. Keep commands checkpointed and separate; do not provide an
automatic full-rollout script.

**Step 3: Run documentation contract and full targeted suite**

Expected: PASS.

**Step 4: Commit**

```bash
git add docs/runbooks/h4-worker-blue-green-handover.md \
  tests/security/test_h4_ml_runtime_artifact.py
git commit -m "docs(deploy): add fail-closed H4 worker handover"
```

### Task 4: Final verification and review

**Files:** none expected.

**Step 1: Run fresh gates**

```bash
/home/daniele/Amber/.venv/bin/pytest -q \
  tests/security/test_h4_ml_runtime_artifact.py \
  tests/unit/test_canary_startup_safety.py \
  tests/unit/test_h4_runtime_binding.py
/home/daniele/Amber/.venv/bin/ruff check \
  tests/security/test_h4_ml_runtime_artifact.py
/home/daniele/Amber/.venv/bin/mypy src
/home/daniele/Amber/.venv/bin/lint-imports
git diff --check origin/main...HEAD
```

Expected: all pass.

**Step 2: Request independent code review**

Review the exact base-to-head diff for queue coverage, Compose inheritance,
read-only mounts, task-drain safety, rollback symmetry, forbidden destructive
commands, and secret exposure. Resolve every Critical/Important finding before
publication.

**Step 3: Publish a PR only after review**

The PR must state that it adds topology/runbook only and does not authorize or
perform production worker mutation. Wait for quality-gate and CodeQL.

**Step 4: Production preflight after merge**

Stage the merge exact in an isolated production worktree, resolve Compose with
the production env without printing secrets, and run dry-runs. Record queue,
Celery active/reserved/scheduled, corpus fingerprints, volume count, memory,
health, restart/OOM, and backup checksum. Show the exact first-replica command
and obtain direct user confirmation before starting it.
