# H4 Canary Ollama Cloud Key Propagation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure both H4 canary services receive the configured Ollama Cloud API key list without broadening their environment exposure.

**Architecture:** Extend the existing explicit Compose environment allowlist for `api-canary` and `worker-canary`. Verify both the source YAML and the fully resolved Compose model using a non-secret sentinel.

**Tech Stack:** Docker Compose YAML, Python, PyYAML, pytest.

---

### Task 1: Add regression coverage

**Files:**
- Modify: `tests/security/test_h4_ml_runtime_artifact.py`

**Step 1: Write the failing static test**

Add a test that parses `deploy/docker-compose.canary.yml` and requires
`OLLAMA_CLOUD_API_KEYS=${OLLAMA_CLOUD_API_KEYS:-}` exactly once in both
`api-canary` and `worker-canary`.

**Step 2: Write the failing resolved-Compose test**

Resolve the base and canary Compose files with a non-secret sentinel value and
the three required volume variables. Require the sentinel to be present in the
resolved environment of both canary services.

**Step 3: Verify RED**

Run:

```bash
pytest -q \
  tests/security/test_h4_ml_runtime_artifact.py::test_canary_explicitly_propagates_ollama_cloud_api_keys_once_per_service \
  tests/security/test_h4_ml_runtime_artifact.py::test_resolved_canary_propagates_ollama_cloud_api_keys
```

Expected: both tests fail because the environment key is absent.

### Task 2: Implement the minimal Compose fix

**Files:**
- Modify: `deploy/docker-compose.canary.yml`

**Step 1: Add the explicit environment entry**

Add this exact entry once to each canary service near the other Ollama
configuration:

```yaml
- OLLAMA_CLOUD_API_KEYS=${OLLAMA_CLOUD_API_KEYS:-}
```

**Step 2: Verify GREEN**

Run the two regression tests from Task 1. Expected: both pass.

**Step 3: Run focused regression gates**

Run:

```bash
pytest -q tests/security/test_h4_ml_runtime_artifact.py
```

Expected: all H4 artifact/canary tests pass.

### Task 3: Verify repository quality

**Files:**
- No production-code changes.

**Step 1: Resolve Compose with a sentinel**

Run `docker compose config --format json` with the three candidate volume
variables and a non-secret `OLLAMA_CLOUD_API_KEYS` sentinel. Inspect only the
two resolved sentinel fields; do not print other environment values.

**Step 2: Run repository gates**

Run `make lint` and the relevant test suite. Any failure unrelated to this
change must be reported rather than hidden.

**Step 3: Review the final diff**

Confirm the diff is limited to the two environment entries, two regression
tests, and these planning documents. Run a secret scan before any local commit.

**Step 4: Commit locally**

Stage only the files touched by this solution and create local commits without
AI attribution. Do not push and do not open a pull request.
