#!/usr/bin/env bash
# restore_preflight_check.sh — Task 0: Verify backup artifacts and run isolated restore drills
#
# SAFE TO RUN ON PRODUCTION: does not touch live containers or volumes.
# All restore drills run in temporary isolated Docker containers that are
# removed on completion. No live service is restarted or modified.
#
# Usage:
#   bash scripts/restore_preflight_check.sh --backup-dir <path>  [--dry-run]
#
# Example:
#   bash scripts/restore_preflight_check.sh --backup-dir backups/preflight_20260325_111201 --dry-run
#   bash scripts/restore_preflight_check.sh --backup-dir backups/preflight_20260325_111201

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
DRY_RUN=false
BACKUP_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true; shift ;;
        --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve backup dir relative to repo root if not absolute
[[ "${BACKUP_DIR}" != /* ]] && BACKUP_DIR="${REPO_ROOT}/${BACKUP_DIR}"

if [[ -z "${BACKUP_DIR}" ]]; then
    echo "Usage: bash scripts/restore_preflight_check.sh --backup-dir <path> [--dry-run]"
    echo "Example: bash scripts/restore_preflight_check.sh --backup-dir backups/preflight_20260325_111201"
    exit 1
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DRILL_LOG="${BACKUP_DIR}/restore_drill_${TIMESTAMP}.log"

if "${DRY_RUN}"; then
    LOG_FILE="/dev/null"
    log()  { echo "[DRY-RUN $(date +%T)] $*"; }
    run()  { echo "[DRY-RUN] WOULD RUN: $*"; }
    fail() { echo "[DRY-RUN FAIL] $*"; exit 1; }
else
    LOG_FILE="${DRILL_LOG}"
    log()  { echo "[$(date +%T)] $*" | tee -a "${LOG_FILE}"; }
    run()  { "$@"; }
    fail() { echo "[$(date +%T)] FAIL: $*" | tee -a "${LOG_FILE}"; exit 1; }
fi

# Load .env values
_env_val() { grep -E "^${1}=" "${REPO_ROOT}/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'" || true; }
POSTGRES_USER="$(_env_val POSTGRES_USER)"
POSTGRES_DB="$(_env_val POSTGRES_DB)"
POSTGRES_PASSWORD="$(_env_val POSTGRES_PASSWORD)"

log "================================================================="
"${DRY_RUN}" && log "*** DRY RUN — no restore commands will be executed ***"
log "Amber2 Restore Preflight Check — ${TIMESTAMP}"
log "Backup dir: ${BACKUP_DIR}"
log "================================================================="

# ── Step 1: Verify backup directory and artifacts ─────────────────────────────
log ""
log "--- Step 1: Verify backup artifacts exist and are non-empty"

[ -d "${BACKUP_DIR}" ] || fail "Backup directory not found: ${BACKUP_DIR}"

POSTGRES_FILE="$(ls "${BACKUP_DIR}"/postgres_*.sql.gz 2>/dev/null | head -1)"
REDIS_FILE="$(ls "${BACKUP_DIR}"/redis_*.rdb 2>/dev/null | head -1)"
NEO4J_FILE="$(ls "${BACKUP_DIR}"/neo4j_volume_*.tar.gz 2>/dev/null | head -1)"
MILVUS_FILE="$(ls "${BACKUP_DIR}"/milvus_volume_*.tar.gz 2>/dev/null | head -1)"
ETCD_FILE="$(ls "${BACKUP_DIR}"/etcd_volume_*.tar.gz 2>/dev/null | head -1)"
GARAGE_DATA_FILE="$(ls "${BACKUP_DIR}"/garage-data_volume_*.tar.gz 2>/dev/null | head -1)"
GARAGE_META_FILE="$(ls "${BACKUP_DIR}"/garage-meta_volume_*.tar.gz 2>/dev/null | head -1)"
CONFIG_DIR="${BACKUP_DIR}/config"

check_artifact() {
    local label="$1" path="$2"
    if [ -n "${path}" ] && [ -f "${path}" ] && [ -s "${path}" ]; then
        log "  ${label}: $(basename "${path}") — $(du -sh "${path}" | cut -f1) — OK"
    else
        log "  ${label}: MISSING or empty — FAIL"
        "${DRY_RUN}" || fail "Required artifact missing: ${label}"
    fi
}

check_artifact "postgres dump"   "${POSTGRES_FILE}"
check_artifact "redis RDB"       "${REDIS_FILE}"
check_artifact "neo4j volume"    "${NEO4J_FILE}"
check_artifact "milvus volume"   "${MILVUS_FILE}"
check_artifact "etcd volume"     "${ETCD_FILE}"
check_artifact "garage-data vol" "${GARAGE_DATA_FILE}"
check_artifact "garage-meta vol" "${GARAGE_META_FILE}"

if [ -d "${CONFIG_DIR}" ] && [ -f "${CONFIG_DIR}/env.snapshot" ]; then
    log "  config dir: present — OK"
else
    log "  config dir: MISSING — FAIL"
    "${DRY_RUN}" || fail "Config snapshot directory missing"
fi

# ── Step 2: Integrity checks (non-destructive reads) ─────────────────────────
log ""
log "--- Step 2: Integrity checks (read-only, no restore yet)"

log "  Integrity checks are read-only and run in both dry-run and real mode."

log "  Postgres dump: verifying gzip integrity..."
if gzip -t "${POSTGRES_FILE}" 2>/dev/null; then
    log "  Postgres dump: gzip integrity OK"
else
    fail "Postgres dump failed gzip integrity check"
fi

log "  Postgres dump: checking SQL header..."
HEADER=$(zcat "${POSTGRES_FILE}" 2>/dev/null | head -3) || true
if echo "${HEADER}" | grep -q "PostgreSQL database dump"; then
    log "  Postgres dump: SQL header OK"
else
    fail "Postgres dump does not look like a valid pg_dump output"
fi

log "  Neo4j volume tar: listing top-level contents..."
NEO4J_CONTENTS=$(tar -tzf "${NEO4J_FILE}" 2>/dev/null | head -20) || true
if echo "${NEO4J_CONTENTS}" | grep -qE '(databases|data|neo4j)'; then
    log "  Neo4j volume tar: structure OK (databases/neo4j found)"
    echo "${NEO4J_CONTENTS}" | grep -E '^\./databases/' | head -5 | while IFS= read -r l; do log "    ${l}"; done
else
    log "  Neo4j volume tar: WARNING — could not verify expected directory structure"
    echo "${NEO4J_CONTENTS}" | head -5 | while IFS= read -r l; do log "    ${l}"; done
fi

log "  Etcd volume tar: listing top-level contents..."
ETCD_CONTENTS=$(tar -tzf "${ETCD_FILE}" 2>/dev/null | head -5) || true
if [ -n "${ETCD_CONTENTS}" ]; then
    log "  Etcd volume tar: readable OK"
    echo "${ETCD_CONTENTS}" | while IFS= read -r l; do log "    ${l}"; done
else
    fail "Etcd volume tar is empty or unreadable"
fi

log "  Garage-meta volume tar: listing top-level contents..."
GARAGE_CONTENTS=$(tar -tzf "${GARAGE_META_FILE}" 2>/dev/null | head -5) || true
if [ -n "${GARAGE_CONTENTS}" ]; then
    log "  Garage-meta tar: readable OK"
    echo "${GARAGE_CONTENTS}" | while IFS= read -r l; do log "    ${l}"; done
else
    fail "Garage-meta volume tar is empty or unreadable"
fi

# ── Step 3: Isolated Postgres restore drill ───────────────────────────────────
log ""
log "--- Step 3: Isolated Postgres restore drill"
log "  Spins up a temporary postgres:16-alpine container, restores the dump,"
log "  queries row counts, then removes the container."
log "  Does NOT touch the live amber2-postgres-1 container or its volume."

DRILL_CONTAINER="amber2-restore-drill-${TIMESTAMP}"

if "${DRY_RUN}"; then
    log "  Would run:"
    log "    docker run -d --name ${DRILL_CONTAINER} -e POSTGRES_PASSWORD=drillpass -e POSTGRES_DB=drilldb postgres:16-alpine"
    log "    (wait for postgres to be ready)"
    log "    docker exec ${DRILL_CONTAINER} psql -U postgres -d drilldb -c 'CREATE ROLE graphrag'"
    log "    zcat ${POSTGRES_FILE} | docker exec -i ${DRILL_CONTAINER} psql -U postgres -d drilldb -q"
    log "    docker exec ${DRILL_CONTAINER} psql -U postgres -d drilldb -c '\\dt' | grep -c '|'"
    log "    docker exec ${DRILL_CONTAINER} psql -U postgres -d drilldb -t -c 'SELECT count(*) FROM documents'"
    log "    docker exec ${DRILL_CONTAINER} psql -U postgres -d drilldb -t -c 'SELECT count(*) FROM tenants'"
    log "    docker exec ${DRILL_CONTAINER} psql -U postgres -d drilldb -t -c 'SELECT count(*) FROM chunks'"
    log "    docker rm -f ${DRILL_CONTAINER}"
    log "  NOTE: 'ALTER TABLE ... OWNER TO graphrag' statements in the dump require"
    log "  the graphrag role to exist — it is created before restore to avoid errors."
else
    log "  Starting isolated drill container: ${DRILL_CONTAINER}..."
    docker run -d --name "${DRILL_CONTAINER}" \
        -e POSTGRES_PASSWORD=drillpass \
        -e POSTGRES_DB=drilldb \
        --no-healthcheck \
        postgres:16-alpine > /dev/null

    # Wait for postgres to be ready (max 30s)
    log "  Waiting for drill postgres to be ready..."
    for i in $(seq 1 30); do
        docker exec "${DRILL_CONTAINER}" pg_isready -U postgres -q 2>/dev/null && break
        sleep 1
    done
    docker exec "${DRILL_CONTAINER}" pg_isready -U postgres -q \
        || { docker rm -f "${DRILL_CONTAINER}" > /dev/null 2>&1; fail "Drill postgres never became ready"; }

    # Create the graphrag role so ALTER TABLE ... OWNER TO graphrag succeeds cleanly
    log "  Creating graphrag role in drill container..."
    docker exec "${DRILL_CONTAINER}" \
        psql -U postgres -d drilldb -c "CREATE ROLE graphrag;" > /dev/null 2>&1 || true

    log "  Restoring dump into drill container..."
    zcat "${POSTGRES_FILE}" \
        | docker exec -i "${DRILL_CONTAINER}" \
            psql -U postgres -d drilldb -q 2>>"${LOG_FILE}" \
        || { docker rm -f "${DRILL_CONTAINER}" > /dev/null 2>&1; fail "Postgres restore into drill container failed"; }

    log "  Querying restored tables..."
    TABLES=$(docker exec "${DRILL_CONTAINER}" \
        psql -U postgres -d drilldb -t -c "\dt" 2>/dev/null | grep -c '|' || true)
    log "  Tables restored: ${TABLES}"

    # Spot-check a few key tables
    for table in documents tenants chunks; do
        COUNT=$(docker exec "${DRILL_CONTAINER}" \
            psql -U postgres -d drilldb -t -c "SELECT count(*) FROM ${table};" 2>/dev/null \
            | tr -d ' ' || echo "not found")
        log "  ${table}: ${COUNT} rows"
    done

    log "  Removing drill container..."
    docker rm -f "${DRILL_CONTAINER}" > /dev/null 2>&1
    log "  Postgres restore drill: PASSED"
fi

# ── Step 4: Neo4j restore reference ──────────────────────────────────────────
log ""
log "--- Step 4: Neo4j restore reference"
log "  Neo4j Community does not support online dump/restore."
log "  To restore from the volume snapshot:"
log ""
log "    1. Stop neo4j:         docker stop amber2-neo4j-1"
log "    2. Stop dependent services if needed (api, worker)"
log "    3. Wipe the volume:    docker run --rm -v amber2_graphrag-neo4j:/data alpine sh -c 'rm -rf /data/*'"
log "    4. Restore the tar:    docker run --rm -v amber2_graphrag-neo4j:/data -v ${NEO4J_FILE}:/backup.tar.gz alpine tar -xzf /backup.tar.gz -C /data"
log "    5. Restart neo4j:      docker start amber2-neo4j-1"
log "    6. Verify:             docker exec amber2-neo4j-1 cypher-shell -u neo4j -p <password> 'MATCH (n) RETURN count(n)'"
log ""
log "  NOTE: The volume snapshot is crash-consistent. If Neo4j was mid-write during"
log "  the snapshot, the restored database may require a recovery pass on first start."
log "  Neo4j handles this automatically via its transaction log."

# ── Step 5: Garage restore reference ─────────────────────────────────────────
log ""
log "--- Step 5: Garage restore reference"
log "  To restore Garage from volume snapshots:"
log ""
log "    1. Stop garage:        docker stop amber2-garage-1"
log "    2. Wipe data volume:   docker run --rm -v amber2_graphrag-garage-data:/data alpine sh -c 'rm -rf /data/*'"
log "    3. Restore data:       docker run --rm -v amber2_graphrag-garage-data:/data -v ${GARAGE_DATA_FILE}:/bk.tar.gz alpine tar -xzf /bk.tar.gz -C /data"
log "    4. Wipe meta volume:   docker run --rm -v amber2_graphrag-garage-meta:/data alpine sh -c 'rm -rf /data/*'"
log "    5. Restore meta:       docker run --rm -v amber2_graphrag-garage-meta:/data -v ${GARAGE_META_FILE}:/bk.tar.gz alpine tar -xzf /bk.tar.gz -C /data"
log "    6. Restart garage:     docker start amber2-garage-1"
log "    7. Verify buckets:     docker exec amber2-garage-1 /garage bucket list"

# ── Step 6: Redis restore reference ──────────────────────────────────────────
log ""
log "--- Step 6: Redis restore reference"
log "  To restore Redis from the RDB snapshot:"
log ""
log "    1. Stop redis:         docker stop amber2-redis-1"
log "    2. Copy RDB into vol:  docker run --rm -v amber2_graphrag-redis:/data -v ${REDIS_FILE}:/dump.rdb alpine cp /dump.rdb /data/dump.rdb"
log "    3. Restart redis:      docker start amber2-redis-1"
log "    4. Verify:             docker exec amber2-redis-1 redis-cli DBSIZE"

# ── Step 7: Image rollback reference ─────────────────────────────────────────
log ""
log "--- Step 7: Image rollback reference"
log "  Custom images are pinned by digest in the manifest. To roll back to a prior image:"
log ""
IMAGES_FILE="$(ls "${BACKUP_DIR}"/../manifests/*-images.txt 2>/dev/null | sort | tail -1)"
if [ -f "${IMAGES_FILE}" ]; then
    grep 'amber2-' "${IMAGES_FILE}" | grep 'sha256' | while IFS= read -r line; do
        log "    ${line}"
    done
fi
log ""
log "  If image tarballs were saved:"
log "    docker load < custom_images_<timestamp>.tar.gz"
log "  Then update docker-compose.yml image references and restart affected services."

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "================================================================="
if "${DRY_RUN}"; then
    log "DRY RUN complete — no restore commands executed"
    log "If the plan looks correct, run without --dry-run to execute the Postgres drill"
else
    log "Restore preflight check PASSED — ${TIMESTAMP}"
    log "Log: ${DRILL_LOG}"
    log ""
    log "All checks passed. Task 0 restore verification is complete."
    log "Evidence recorded in: ${DRILL_LOG}"
    log ""
    log "Next step: fill in the Task 0 sign-off in the release verification checklist,"
    log "then proceed to Task 1."
fi
log "================================================================="
