# CI Tests (GitHub Actions) - Design

Date: 2026-01-29
Status: Accepted

## Context
The repository has documented backend and frontend testing commands, but no CI workflows. We want a first, fast CI pass that provides signal without requiring services or secrets.

## Goals
- Add GitHub Actions CI that runs on push and pull request.
- Keep the initial run time short (lint + unit tests only).
- Use project-standard runtimes (Python 3.11, Node 20 LTS).
- Provide clear, separate signals for backend and frontend.

## Non-goals
- Integration tests (service dependencies).
- Frontend E2E tests (Playwright).
- Coverage reporting, artifact uploads, or security scanning.

## Options Considered
1. **Single workflow with two jobs (recommended)**
   - Pros: simplest to maintain, parallel jobs, easy to read.
   - Cons: one file for both stacks.
2. Split workflows (backend.yml + frontend.yml)
   - Pros: separation by domain.
   - Cons: more files and duplicated setup.
3. Matrix builds (multi-OS or multi-version)
   - Pros: higher coverage.
   - Cons: slower and noisy for a first pass.

## Decision
Use a single workflow (`.github/workflows/ci.yml`) with two parallel jobs: `backend` and `frontend`.

## Workflow Details
- **Triggers**: `push` and `pull_request` for all branches.
- **Concurrency**: cancel in-progress runs per branch to avoid stale runs.
- **Permissions**: read-only.
- **Backend job**:
  - Setup Python 3.11.
  - Cache pip based on `requirements.txt` and `pyproject.toml`.
  - Install dev deps via `pip install -e ".[dev]"`.
  - Run `make lint` (ruff) then `make test-unit`.
- **Frontend job**:
  - Setup Node 20.
  - Cache npm using `frontend/package-lock.json`.
  - Run `npm ci`, then `npm run lint` and `npm run test`.
  - Set `CI=true`.
- **Timeouts**: 15 minutes per job.

## Risks and Mitigations
- **Hidden service dependencies in unit tests**: keep to unit tests only and refactor tests to use mocks if needed.
- **Flaky install steps**: use caches keyed to lockfiles and requirements files.

## Future Extensions
- Add integration tests with Docker services.
- Add Playwright E2E tests (likely on main or nightly schedule).
- Optional coverage reporting or artifact uploads.
