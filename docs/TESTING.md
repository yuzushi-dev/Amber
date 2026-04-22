# Testing in Amber

## Overview

Amber employs a comprehensive testing strategy covering backend services,
frontend interfaces, and end-to-end user flows. This guide details how to run,
debug, and extend test coverage.

## Quick Start

### Backend

```bash
# Run all unit tests (fast)
make test-unit

# Run integration tests (requires local services; Docker Compose is one option)
make test-int

# Run everything
make test
```

### Frontend

```bash
cd frontend

# Run unit tests
npm run test

# Run End-to-End tests (requires running backend)
npm run test:e2e
```

## Backend Testing (`/tests`)

The backend testing stack is built on `pytest` with locally running service
dependencies for integration tests.

### 1. Unit Tests (`tests/unit`)

- **Focus**: Individual functions, classes, and isolated components.
- **Mocking**: External dependencies (Neo4j, Garage, Milvus) are mocked in
  `conftest.py` or within test files.
- **Speed**: Designed to run fast (~seconds).
- **Command**: `pytest tests/unit`

### 2. Integration Tests (`tests/integration`)

- **Focus**: Service interactions, database persistence, and API flows.
- **Infrastructure**: Uses locally running services (see
  `tests/integration/conftest.py`).
  - PostgreSQL (default: `localhost:5433`)
  - Redis (`localhost:6379`)
  - Neo4j (`localhost:7687`)
  - Milvus (`localhost:19530`)
  - Garage S3 API (`localhost:3900`)
- **Requirements**: Local dependencies running or override env vars before `pytest`.
- **Command**: `pytest tests/integration`

### 3. Regression Tests (`tests/regression`)

- **Focus**: High-level system quality checks and bug repros.

### 4. Security Tests (`tests/security`) — 121 tests

Added in v1.1.0. Covers all security hardening layers end-to-end:

| File | Coverage |
|---|---|
| `test_task3_control_plane.py` | Admin control-plane isolation |
| `test_task4_rules_tenancy.py` | Global rule tenancy enforcement |
| `test_task5_fallbacks.py` | Fail-closed fallback behaviour |
| `test_task6_isolation.py` | Cross-tenant data isolation |
| `test_task7_keyring.py` | Dual-secret keyring and key rotation |
| `test_task8_sse_ticket.py` | SSE one-time-use tickets (30s TTL, replay rejection) |
| `test_task9_fail_closed.py` | Redis-unavailable 503 path for rate and LLM limiters |
| `test_task9_community_throttle.py` | Community endpoint throttling |
| `test_task10_db_layer.py` | DB-layer RLS and graphrag_app role enforcement |
| `test_task11_connector_creds.py` | Connector credential Fernet encryption |
| `test_admin_route_guards.py` | Admin route authentication guards |
| `test_agent_tool_authorization.py` | Agent tool authorization checks |
| `test_conv_history_gaps.py` | Conversation history privacy gaps |
| `test_gap_fixes.py` | Security gap fix verification |
| `test_graph_security.py` | Knowledge graph access control |
| `test_injection.py` | Prompt injection resistance |
| `test_pii.py` | PII handling and redaction |
| `test_remediation.py` | Remediation flow security |

- **Command**: `pytest tests/security`

### 5. E2E API Tests (`tests/e2e`) — 71 tests

Full-stack API integration tests covering critical multi-service flows:

| File | Coverage |
|---|---|
| `test_auth_matrix.py` | Role/scope authentication matrix |
| `test_chat_history.py` | Chat history retrieval and privacy |
| `test_graph_sync.py` | Graph synchronization flows |
| `test_isolation.py` | Tenant isolation end-to-end |
| `test_key_tiers.py` | API key tier enforcement |
| `test_pipeline.py` | Full ingestion + retrieval pipeline |

- **Command**: `pytest tests/e2e`

### Pytest Markers

- `@pytest.mark.unit`: Isolated unit tests.
- `@pytest.mark.integration`: Tests requiring Docker services.
- `@pytest.mark.asyncio`: For async FastAPI/DB tests.

## Frontend Testing (`/frontend`)

The frontend uses `Vitest` for unit testing and `Playwright` for E2E.

### 1. Unit/Component Tests

- **Tool**: Vitest + React Testing Library.
- **Focus**: Component rendering, hook logic, and state management.
- **Environment**: `happy-dom`.
- **Command**: `npm run test`

### 2. End-to-End (E2E) Tests (`tests/e2e`)

- **Tool**: Playwright.
- **Focus**: Critical user flows (Ingestion, Chat, Admin).
- **Configuration**: `playwright.config.ts`.
- **Command**: `npm run test:e2e` (runs in headless mode by default).

### Key E2E Scenarios

- **Authentication**: Usage of login/logout flows.
- **Pipelines**: Document upload and chat response verification.
- **Maintenance**: Admin panel accessibility.

## CI/CD Pipeline

A repository workflow is checked in at
`.github/workflows/quality-gate.yml`. It runs:

1. Backend: `ruff`, `lint-imports`, `mypy`, `pytest -q tests/unit`.
2. Frontend: `npm run lint`, `npm run build`, `npm run test`.

The workflow delegates to `bash scripts/verify.sh all` so local and CI quality
gates stay aligned.

### Pre-push Enforcement

This repository includes `.pre-commit-config.yaml` with `pre-push` hooks for:

1. `bash scripts/verify.sh backend`
2. `bash scripts/verify.sh frontend`

Setup:

```bash
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/pre-commit install --hook-type pre-push
```
