# H4 Production Volume Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow the reviewed H4 builder to validate an exact-SHA production volume without weakening its mirror-only default or creating/deleting volumes.

**Architecture:** Extend the shell CLI with an explicit production authorization mode. Derive the sole accepted production volume name from the fixed H3 source ref and current Git HEAD, then require a full-HEAD `amber.h4.candidate-ref` label before any install or preload work.

**Tech Stack:** Bash, Docker CLI, Git, pytest contract/subprocess tests, Markdown runbook.

---

### Task 1: Specify the production CLI fail-closed behavior

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`

1. Add a subprocess test proving a production-prefixed volume without
   `--authorize-production` fails before Docker access.
2. Add a subprocess test computing `git rev-parse HEAD` and proving the exact
   derived name plus authorization advances to the existing local-Docker guard.
3. Add a test proving an authorized but non-derived production name is refused.
4. Run the three tests and verify RED because production mode does not exist.

### Task 2: Implement the minimal production volume guard

**Files:**
- Modify: `scripts/h4_ml_runtime_candidate.sh`
- Test: `tests/security/test_h4_ml_runtime_artifact.py`

1. Resolve and validate the current 40-hex Git HEAD.
2. Parse only the existing mirror forms or the exact production forms with
   `--authorize-production` in the fixed positions documented by the CLI.
3. Derive the exact production volume name from H3 ref plus HEAD short SHA.
4. Preserve exact mirror equality; require exact production equality.
5. In production mode, read `amber.h4.candidate-ref` and require the full HEAD.
6. Run the focused tests and verify GREEN.

### Task 3: Pin the static safety contract and documentation

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`
- Modify: `docs/H4_ML_RUNTIME_ROLLOUT.md`

1. Add static assertions that production authorization, dynamic HEAD,
   candidate-ref verification, and the no-create/no-delete contract remain.
2. Document the exact volume-create labels separately from install/preload.
3. State that each production mutation still needs direct approval.
4. Run the full H4 security test file.

### Task 4: Regression verification and commit

**Files:**
- Verify all changed files.

1. Run `uv lock --check`.
2. Run the H4 binding/recovery/sparse targeted suite.
3. Run `bash scripts/verify.sh all`.
4. Run `git diff --check` and review the diff.
5. Commit only the design, implementation plan, tests, script, and rollout doc.

