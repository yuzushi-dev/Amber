#!/usr/bin/env bash
# smoke_production_readonly.sh — read-only smoke tests for the Amber2 API
#
# SAFE: only reads (GET requests). Does not mutate any data.
# Run against the live stack, canary, or any target URL.
#
# Usage:
#   bash scripts/smoke_production_readonly.sh [OPTIONS]
#
# Options:
#   --base-url URL        API base URL (default: http://127.0.0.1:8000)
#   --frontend-url URL    Frontend URL (default: http://127.0.0.1:3000)
#   --api-key KEY         API key for authenticated checks
#                         (falls back to DEV_API_KEY in .env if not given)
#   --check-auth-gates    Run 401/403 auth gate checks (requires --api-key)
#                         Enable after Wave 1 is deployed.
#
# Examples:
#   # Test live stack (default ports)
#   bash scripts/smoke_production_readonly.sh
#
#   # Test canary directly (exposed on 8001 during pre-cutover phase)
#   bash scripts/smoke_production_readonly.sh --base-url http://127.0.0.1:8001
#
#   # Full check including auth gates (post-Wave 1)
#   bash scripts/smoke_production_readonly.sh --check-auth-gates

set -euo pipefail

# ── Argument parsing ───────────────────────────────────────────────────────────
BASE_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:3000"
API_KEY=""
CHECK_AUTH_GATES=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-url)        BASE_URL="$2";     shift 2 ;;
        --frontend-url)    FRONTEND_URL="$2"; shift 2 ;;
        --api-key)         API_KEY="$2";      shift 2 ;;
        --check-auth-gates) CHECK_AUTH_GATES=true; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load API key from .env if not provided
if [[ -z "${API_KEY}" ]]; then
    API_KEY="$(grep -E '^DEV_API_KEY=' "${REPO_ROOT}/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'" || true)"
fi

PASS=0
FAIL=0
WARN=0

pass() { echo "  [PASS] $*"; (( PASS++ )) || true; }
fail() { echo "  [FAIL] $*"; (( FAIL++ )) || true; }
warn() { echo "  [WARN] $*"; (( WARN++ )) || true; }

check_http() {
    local label="$1" url="$2" expected_code="$3"
    shift 3
    local extra_args=("$@")
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${extra_args[@]}" "${url}" 2>/dev/null || echo "000")
    if [[ "${code}" == "${expected_code}" ]]; then
        pass "${label}: HTTP ${code}"
        return 0
    else
        fail "${label}: expected HTTP ${expected_code}, got ${code}"
        return 1
    fi
}

check_body() {
    local label="$1" url="$2" pattern="$3"
    shift 3
    local extra_args=("$@")
    local body
    body=$(curl -s --max-time 10 "${extra_args[@]}" "${url}" 2>/dev/null || true)
    if echo "${body}" | grep -q "${pattern}"; then
        pass "${label}: body contains '${pattern}'"
        return 0
    else
        fail "${label}: body missing '${pattern}' (got: ${body:0:100})"
        return 1
    fi
}

echo "================================================================="
echo "Amber2 Smoke Test"
echo "API:      ${BASE_URL}"
echo "Frontend: ${FRONTEND_URL}"
echo "Auth key: $([ -n "${API_KEY}" ] && echo "<set>" || echo "<not set>")"
echo "Auth gate checks: ${CHECK_AUTH_GATES}"
echo "================================================================="
echo ""

# ── 1. Health checks ──────────────────────────────────────────────────────────
echo "--- 1. Health checks"
check_http "GET /health"       "${BASE_URL}/health"       "200"
check_body "GET /health body"  "${BASE_URL}/health"       '"status"'
check_http "GET /health/ready" "${BASE_URL}/health/ready" "200"
check_body "GET /health/ready body" "${BASE_URL}/health/ready" '"status"'
echo ""

# ── 2. Frontend reachability ──────────────────────────────────────────────────
echo "--- 2. Frontend reachability"
FRONTEND_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${FRONTEND_URL}/" 2>/dev/null || echo "000")
if [[ "${FRONTEND_CODE}" =~ ^[23] ]]; then
    pass "GET ${FRONTEND_URL}/: HTTP ${FRONTEND_CODE}"
else
    fail "GET ${FRONTEND_URL}/: HTTP ${FRONTEND_CODE} (expected 2xx or 3xx)"
fi
echo ""

# ── 3. Authenticated read-only query ─────────────────────────────────────────
echo "--- 3. Authenticated read-only query"
if [[ -n "${API_KEY}" ]]; then
    check_http "GET /v1/documents (auth)" \
        "${BASE_URL}/v1/documents?page=1&page_size=1" "200" \
        -H "X-API-Key: ${API_KEY}"
    check_body "GET /v1/documents body" \
        "${BASE_URL}/v1/documents?page=1&page_size=1" \
        '"' \
        -H "X-API-Key: ${API_KEY}"
else
    warn "No API key available — skipping authenticated query check"
    warn "Set DEV_API_KEY in .env or pass --api-key to enable this check"
fi
echo ""

# ── 4. Unauthenticated request is rejected ───────────────────────────────────
echo "--- 4. Unauthenticated rejection"
check_http "GET /v1/admin/tenants (no key) → 401" \
    "${BASE_URL}/v1/admin/tenants" "401"
echo ""

# ── 5. Auth gate checks (post-Wave 1) ────────────────────────────────────────
echo "--- 5. Auth gate checks (post-Wave 1)"
if "${CHECK_AUTH_GATES}"; then
    if [[ -z "${API_KEY}" ]]; then
        fail "Auth gate checks require --api-key"
    else
        # After Wave 1: DEV_API_KEY is super-admin only; tenant-admin keys should get 403
        # Super-admin key should still reach admin routes
        check_http "GET /v1/admin/tenants (super-admin key) → 200" \
            "${BASE_URL}/v1/admin/tenants" "200" \
            -H "X-API-Key: ${API_KEY}"

        # Check that admin-only routes return 401 without auth (belt-and-suspenders)
        check_http "GET /v1/admin/jobs (no key) → 401" \
            "${BASE_URL}/v1/admin/jobs" "401"

        # NOTE: To test 403 for tenant-admin keys, pass a tenant-scoped key via --api-key
        # and compare. Full tenant-user 403 gate test requires a separate tenant key.
        warn "Tenant-user 403 gate not checked — pass a tenant-user --api-key to verify"
    fi
else
    warn "Auth gate checks skipped (add --check-auth-gates to enable; requires Wave 1 deployed)"
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "================================================================="
echo "Results: ${PASS} PASS, ${FAIL} FAIL, ${WARN} WARN"
if [[ "${FAIL}" -gt 0 ]]; then
    echo "SMOKE: FAILED — ${FAIL} check(s) failed"
    exit 1
else
    echo "SMOKE: PASSED"
fi
echo "================================================================="
