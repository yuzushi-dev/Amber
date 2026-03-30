#!/usr/bin/env bash
# cutover.sh — Switch nginx traffic between live and canary API
#
# SAFE: only modifies nginx upstream config and reloads nginx.
# Does NOT restart, stop, or recreate any application container.
#
# Usage (from /root/amber2):
#   bash deploy/cutover.sh --to <live|canary> [--dry-run]
#
# Options:
#   --to live    Route all API traffic to the primary api container
#   --to canary  Route all API traffic to the api-canary container
#   --dry-run    Print what would happen without applying changes
#
# Prerequisites for --to canary:
#   - api-canary must be running and healthy
#   - smoke tests pass against http://127.0.0.1:8001 (direct canary port)
#
# Full workflow:
#   1. Start canary:
#      docker compose -f docker-compose.yml -f deploy/docker-compose.canary.yml \
#          up -d api-canary
#
#   2. Smoke test canary directly (no nginx involved):
#      bash scripts/smoke_production_readonly.sh --base-url http://127.0.0.1:8001
#
#   3. Switch nginx to canary:
#      bash deploy/cutover.sh --to canary --dry-run
#      bash deploy/cutover.sh --to canary
#
#   4. Rollback if needed:
#      bash deploy/cutover.sh --to live

set -euo pipefail

TARGET=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --to)      TARGET="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NGINX_CONF_DIR="${REPO_ROOT}/deploy/nginx/conf.d"
UPSTREAM_ACTIVE="${NGINX_CONF_DIR}/upstream.conf"
UPSTREAM_LIVE="${REPO_ROOT}/deploy/nginx/upstreams/live.conf"
UPSTREAM_CANARY="${REPO_ROOT}/deploy/nginx/upstreams/canary.conf"
NGINX_CONTAINER="amber2-nginx-1"
SMOKE_SCRIPT="${REPO_ROOT}/scripts/smoke_production_readonly.sh"

if [[ -z "${TARGET}" ]]; then
    echo "Usage: bash deploy/cutover.sh --to <live|canary> [--dry-run]"
    exit 1
fi

if [[ "${TARGET}" != "live" && "${TARGET}" != "canary" ]]; then
    echo "Unknown target: ${TARGET}. Use 'live' or 'canary'."
    exit 1
fi

log()       { echo "[$(date +%T)] $*"; }
run()       { if "${DRY_RUN}"; then echo "[DRY-RUN] WOULD RUN: $*"; else "$@"; fi; }
prefail()   {
    # In dry-run mode, pre-flight failures are warnings (show plan regardless).
    if "${DRY_RUN}"; then echo "[DRY-RUN WARN] Pre-flight: $*"; else echo "[FAIL] $*"; exit 1; fi
}
fail()      { echo "[FAIL] $*"; exit 1; }

log "================================================================="
"${DRY_RUN}" && log "*** DRY RUN — no changes will be applied ***"
log "Amber2 Canary Cutover"
log "Target: ${TARGET}"
log "================================================================="

# ── Pre-flight: nginx container must be running ────────────────────────────────
log ""
log "--- Pre-flight checks"

if ! docker inspect "${NGINX_CONTAINER}" > /dev/null 2>&1; then
    prefail "nginx container '${NGINX_CONTAINER}' not found."
    "${DRY_RUN}" && log "  (nginx will be started with: docker compose up -d nginx api frontend)"
else
    NGINX_STATUS=$(docker inspect --format '{{.State.Status}}' "${NGINX_CONTAINER}" 2>/dev/null || echo "unknown")
    if [[ "${NGINX_STATUS}" != "running" ]]; then
        prefail "nginx container is ${NGINX_STATUS}, expected running"
    else
        log "  nginx container: ${NGINX_STATUS} — OK"
    fi
fi

# ── Pre-flight: canary-specific checks ────────────────────────────────────────
if [[ "${TARGET}" == "canary" ]]; then
    CANARY_CONTAINER="amber2-api-canary-1"
    if ! docker inspect "${CANARY_CONTAINER}" > /dev/null 2>&1; then
        prefail "api-canary container '${CANARY_CONTAINER}' not found."
        "${DRY_RUN}" && log "  (start with: docker compose -f docker-compose.yml -f deploy/docker-compose.canary.yml up -d api-canary)"
    else
        CANARY_STATUS=$(docker inspect --format '{{.State.Status}}' "${CANARY_CONTAINER}" 2>/dev/null || echo "unknown")
        if [[ "${CANARY_STATUS}" != "running" ]]; then
            prefail "api-canary container is ${CANARY_STATUS}, expected running"
        else
            log "  api-canary container: ${CANARY_STATUS} — OK"
        fi
    fi

    # Verify canary passes smoke tests at its direct port before switching nginx
    log "  Running smoke tests against canary (http://127.0.0.1:8001)..."
    if "${DRY_RUN}"; then
        log "  [DRY-RUN] WOULD RUN: bash scripts/smoke_production_readonly.sh --base-url http://127.0.0.1:8001"
    else
        bash "${SMOKE_SCRIPT}" --base-url http://127.0.0.1:8001 \
            || fail "Canary smoke tests failed. Aborting nginx cutover."
    fi
fi

# ── Select upstream config ─────────────────────────────────────────────────────
log ""
log "--- Upstream switch"

if [[ "${TARGET}" == "live" ]]; then
    SOURCE_CONF="${UPSTREAM_LIVE}"
    TARGET_LABEL="api:8000 (live)"
else
    SOURCE_CONF="${UPSTREAM_CANARY}"
    TARGET_LABEL="api-canary:8000 (canary)"
fi

log "  Switching upstream to: ${TARGET_LABEL}"
log "  Writing ${SOURCE_CONF} → ${UPSTREAM_ACTIVE}"

if "${DRY_RUN}"; then
    echo "[DRY-RUN] WOULD RUN: cat ${SOURCE_CONF} > ${UPSTREAM_ACTIVE}"
    echo "[DRY-RUN] New upstream.conf content:"
    cat "${SOURCE_CONF}" | sed 's/^/    /'
else
    # Overwrite in-place so the bind-mounted file in the nginx container is updated
    cat "${SOURCE_CONF}" > "${UPSTREAM_ACTIVE}"
fi

# ── Reload nginx ───────────────────────────────────────────────────────────────
log "  Reloading nginx..."
run docker exec "${NGINX_CONTAINER}" nginx -t
run docker exec "${NGINX_CONTAINER}" nginx -s reload
log "  nginx reloaded — upstream now: ${TARGET_LABEL}"

# ── Post-cutover smoke test ───────────────────────────────────────────────────
log ""
log "--- Post-cutover smoke test (http://127.0.0.1:8000)"
if "${DRY_RUN}"; then
    log "  [DRY-RUN] WOULD RUN: bash scripts/smoke_production_readonly.sh"
else
    bash "${SMOKE_SCRIPT}" \
        || { log "SMOKE TESTS FAILED after cutover to ${TARGET}."; \
             log "Rolling back to live upstream..."; \
             cat "${UPSTREAM_LIVE}" > "${UPSTREAM_ACTIVE}"; \
             docker exec "${NGINX_CONTAINER}" nginx -s reload; \
             fail "Rolled back to live. Investigate canary before retrying."; }
fi

# ── Summary ────────────────────────────────────────────────────────────────────
log ""
log "================================================================="
if "${DRY_RUN}"; then
    log "DRY RUN complete — no changes applied"
    log "Remove --dry-run to execute the cutover"
else
    log "Cutover to '${TARGET}' complete — PASSED"
    log ""
    if [[ "${TARGET}" == "canary" ]]; then
        log "Traffic is now routing to api-canary."
        log "Monitor logs: docker compose logs --tail 50 -f api-canary"
        log "Rollback:     bash deploy/cutover.sh --to live"
    else
        log "Traffic is now routing to api (live)."
        log "Stop canary:  docker compose -f docker-compose.yml -f deploy/docker-compose.canary.yml stop api-canary worker-canary"
    fi
fi
log "================================================================="
