# H4 Docker Root Storage Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the H4 storage gate measure the filesystem used by the guarded local Docker daemon instead of hardcoded `/var/lib/docker`.

**Architecture:** Add one fail-closed shell resolver for `DockerRootDir` and make `free_bytes` use its validated absolute directory. Test the real shell functions through a prefix harness with a stubbed `docker_local`, plus retain static safety-contract assertions.

**Tech Stack:** Bash, Docker CLI, pytest, Python subprocess tests.

---

### Task 1: Add failing Docker-root storage tests

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`

**Step 1: Update the static contract**

Require `docker_local info --format '{{ .DockerRootDir }}'`, require `df` to use
the resolved root with `--`, reject `/var/lib/docker`, and reject an
`H4_DOCKER_ROOT` operator override.

**Step 2: Add behavioral shell tests**

Build a temporary harness from the builder prefix before CLI parsing, override
`docker_local` to return `TEST_DOCKER_ROOT`, and invoke `free_bytes`. Use a fake
`df` to assert an existing custom root is the exact measured argument. Add
parameterized relative, multiline, and nonexistent roots and assert failure
before `df` executes.

**Step 3: Run tests to verify RED**

Run:
`./.venv/bin/pytest -q tests/security/test_h4_ml_runtime_artifact.py -k 'builder_is_scoped or docker_root'`

Expected: failures because the builder still hardcodes `/var/lib/docker` and
does not validate daemon output.

### Task 2: Implement the minimal fail-closed resolver

**Files:**
- Modify: `scripts/h4_ml_runtime_candidate.sh`

**Step 1: Add `docker_root_dir`**

Resolve the root with guarded `docker_local info`, then require non-empty,
absolute, single-line, control-character-free output and an existing directory.

**Step 2: Change `free_bytes`**

Resolve the validated Docker root and call
`df -B1 --output=avail -- "$docker_root"`, preserving the existing numeric
thresholds and proof fields.

**Step 3: Run focused tests to verify GREEN**

Run the RED command again. Expected: all selected tests pass.

**Step 4: Commit the implementation**

Stage only the test and builder, then commit `fix: measure H4 storage on Docker root`.

### Task 3: Verify and publish

**Files:**
- Modify: `docs/H4_ML_RUNTIME_ROLLOUT.md`

**Step 1: Document daemon-derived storage measurement**

Explain fail-closed Docker-root discovery and absence of an operator override.

**Step 2: Run verification**

Run Bash syntax, the full H4 security file, targeted related unit tests,
`uv lock --check`, `git diff --check`, and `bash scripts/verify.sh all`.

**Step 3: Commit docs and publish PR**

Push without force, open a PR to `main`, and wait for quality-gate and all
CodeQL jobs. Do not merge or retry production without separate direct approval.
