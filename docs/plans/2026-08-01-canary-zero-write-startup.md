# Canary Zero-Write Startup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent canary startup from creating API keys or worktree-namespaced datastore volumes.

**Architecture:** Gate the sole known API startup write behind `AMBER_CANARY`, while retaining read-only compatibility checks. Fix the canary Compose project identity at both overlay and documented command layers.

**Tech Stack:** Python async lifespan, Docker Compose, pytest, PyYAML.

---

### Task 1: Prove API canary bootstrap is forbidden

**Files:**
- Create: `tests/unit/test_canary_startup_safety.py`
- Modify: `src/api/main.py`

1. Write an async test that sets `AMBER_CANARY=true`, calls the bootstrap helper with a sentinel session, and proves `ApiKeyService` is never constructed.
2. Run the test and observe RED because the helper does not exist.
3. Add the minimal helper and replace the direct lifespan call.
4. Run the focused test and relevant API-key tests GREEN.
5. Commit.

### Task 2: Stabilize Compose project identity

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`
- Modify: `deploy/docker-compose.canary.yml`

1. Write a contract requiring top-level `name: amber2` and `--project-name amber2` in every usage/rollback command example.
2. Run the test and observe RED.
3. Add the project name and update examples.
4. Render Compose from a differently named worktree and prove the resolved project and datastore volume names are `amber2*`.
5. Commit.

### Task 3: Verify and publish

**Files:**
- Verify all changed code and tests.

1. Run focused safety tests, the full H4 security file, shell syntax, and lock check.
2. Install frontend dependencies in the isolated worktree and run `bash scripts/verify.sh all`.
3. Request independent code review and address all Important/Critical findings.
4. Push and open a PR. Do not merge or mutate production without direct user confirmation.
