# H4 Canary Artifact Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make both H4 canary services use the preloaded cache inside the immutable H4 artifact without creating or mounting a per-worktree host cache.

**Architecture:** Keep the existing read-only H4 volume as the single package and model-cache boundary. Configure Hugging Face variables to paths within that mount and remove the redundant host bind from API and worker.

**Tech Stack:** Docker Compose, Python/PyYAML security contract tests, pytest.

---

### Task 1: Add the cache ownership contract

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`

1. Add a test that parses `deploy/docker-compose.canary.yml` and, for each canary service, requires `HF_HOME=/app/.packages-h4/hf-cache` and `HUGGINGFACE_HUB_CACHE=/app/.packages-h4/hf-cache/hub`.
2. Require that neither service mounts `./.cache/huggingface`.
3. Run the focused test and verify it fails on the current overlay because the API variable is missing, the worker points to the host bind, and both bind mounts remain.

### Task 2: Route both services to the artifact cache

**Files:**
- Modify: `deploy/docker-compose.canary.yml`

1. Add both cache variables to API and worker.
2. Remove both worktree cache bind mounts.
3. Run the focused test and complete H4 security test file; both must pass.

### Task 3: Verify and publish

**Files:**
- Verify: `deploy/docker-compose.canary.yml`
- Verify: `tests/security/test_h4_ml_runtime_artifact.py`

1. Render Compose with explicit H3/H4 volume names and verify both services resolve the artifact cache variables with no host cache mount.
2. Run shell syntax, lock check, `git diff --check`, and `bash scripts/verify.sh all`.
3. Commit the implementation, request review, push the branch, and open a PR. Do not merge or mutate production without direct user confirmation.
