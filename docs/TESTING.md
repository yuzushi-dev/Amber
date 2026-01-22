# Testing in Amber 2.0

## Overview

Amber 2.0 employs a comprehensive testing strategy covering backend services,
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
- **Mocking**: External dependencies (Neo4j, MinIO, Milvus) are mocked in
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
  - MinIO (`localhost:9000`)
- **Requirements**: Local dependencies running or override env vars before `pytest`.
- **Command**: `pytest tests/integration`

### 3. Regression Tests (`tests/regression`)

- **Focus**: High-level system quality checks and bug repros.

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

No CI workflows are checked into this repository. If you add one, consider:

1. **Linting**: `ruff` (Backend) + `eslint` (Frontend).
2. **Backend Tests**: Unit and regression tests by default; integration tests
   when services are available.
3. **Frontend Tests**: `npm run test` and `npm run test:e2e`.
4. **Security**: Dependency and secret scanning (optional).
