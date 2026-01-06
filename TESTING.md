# Testing in Amber 2.0

Amber 2.0 employs a comprehensive testing strategy covering backend services, frontend interfaces, and end-to-end user flows. This guide details how to run, debug, and extend test coverage.

## 🧪 Quick Start

**Backend**
```bash
# Run all unit tests (fast)
make test-unit

# Run integration tests (requires Docker)
make test-int

# Run everything
make test
```

**Frontend**
```bash
cd frontend

# Run unit tests
npm run test

# Run End-to-End tests (requires running backend)
npm run test:e2e
```

---

## 🏗️ Backend Testing (`/tests`)

The backend testing stack is built on `pytest` and `testcontainers`.

### 1. Unit Tests (`tests/unit`)
- **Focus**: Individual functions, classes, and isolated components.
- **Mocking**: External dependencies (Neo4j, MinIO, Milvus) are mocked in `conftest.py` or within test files.
- **Speed**: Designed to run fast (~seconds).
- **Command**: `pytest tests/unit`

### 2. Integration Tests (`tests/integration`)
- **Focus**: Service interactions, database persistence, and API flows.
- **Infrastructure**: Uses `testcontainers` to spin up ephemeral Docker containers for:
    - PostgreSQL
    - Neo4j
    - MinIO
- **Requirements**: Docker Engine must be running.
- **Command**: `pytest tests/integration`

### 3. Regression Tests (`tests/regression`)
- **Focus**: High-level system quality checks and bug repros.

### Pytest Markers
- `@pytest.mark.unit`: Isolated unit tests.
- `@pytest.mark.integration`: Tests requiring Docker services.
- `@pytest.mark.asyncio`: for async FastAPI/DB tests.

---

## 🎨 Frontend Testing (`/frontend`)

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

**Key E2E Scenarios**:
- **Authentication**: Usage of login/logout flows.
- **Pipelines**: Document upload and chat response verification.
- **Maintenance**: Admin panel accessibility.

---

## 🚀 CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) enforces quality on every PR:

1.  **Linting**: `ruff` (Backend) + `eslint` (Frontend).
2.  **Backend Tests**: Runs unit and regression tests.
3.  **Frontend Tests**: Runs unit and E2E tests.
4.  **Security**: Checks for known vulnerabilities (planned).

> **Note**: Integration tests requiring heavy services are optimized to run where Docker is available.

