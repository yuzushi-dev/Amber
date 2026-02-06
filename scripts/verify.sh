#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-all}"

RUFF_BIN="${RUFF_BIN:-./.venv/bin/ruff}"
IMPORT_LINTER_BIN="${IMPORT_LINTER_BIN:-./.venv/bin/lint-imports}"
MYPY_BIN="${MYPY_BIN:-./.venv/bin/mypy}"
PYTEST_BIN="${PYTEST_BIN:-./.venv/bin/pytest}"

require_tool() {
  local tool="$1"
  local install_hint="$2"
  if [[ "$tool" == */* ]]; then
    if [[ ! -x "$tool" ]]; then
      echo "Missing required tool: $tool"
      echo "$install_hint"
      exit 1
    fi
  else
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "Missing required tool: $tool"
      echo "$install_hint"
      exit 1
    fi
  fi
}

run_backend_checks() {
  echo "==> Backend: ruff"
  "$RUFF_BIN" check src tests

  echo "==> Backend: import-linter"
  "$IMPORT_LINTER_BIN"

  echo "==> Backend: mypy"
  "$MYPY_BIN" src

  echo "==> Backend: pytest (unit)"
  "$PYTEST_BIN" -q tests/unit
}

run_frontend_checks() {
  echo "==> Frontend: eslint"
  npm --prefix frontend run lint

  echo "==> Frontend: build"
  npm --prefix frontend run build

  echo "==> Frontend: tests"
  npm --prefix frontend run test
}

require_tool "$RUFF_BIN" "Install backend dev dependencies: ./.venv/bin/pip install -e '.[dev]'"
require_tool "$IMPORT_LINTER_BIN" "Install backend dev dependencies: ./.venv/bin/pip install -e '.[dev]'"
require_tool "$MYPY_BIN" "Install backend dev dependencies: ./.venv/bin/pip install -e '.[dev]'"
require_tool "$PYTEST_BIN" "Install backend dev dependencies: ./.venv/bin/pip install -e '.[dev]'"
require_tool "npm" "Install Node.js and npm, then run npm --prefix frontend install"

case "$MODE" in
  backend)
    run_backend_checks
    ;;
  frontend)
    run_frontend_checks
    ;;
  all)
    run_backend_checks
    run_frontend_checks
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: bash scripts/verify.sh [backend|frontend|all]"
    exit 1
    ;;
esac

echo "Verification checks completed for mode: $MODE"
