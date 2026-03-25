#!/usr/bin/env bash
# backup_preflight.sh — Task 0: Preflight snapshot before any security rollout
#
# SAFE TO RUN ON PRODUCTION: does not stop or restart any service.
# All data captures are online (pg_dump, Redis BGSAVE) or crash-consistent
# volume tars. Neo4j, Milvus, etcd, and Garage are volume-snapshot only.
#
# Usage:
#   bash scripts/backup_preflight.sh            # real run
#   bash scripts/backup_preflight.sh --dry-run  # print what would happen, write nothing
#
# Run from /root/amber2

set -euo pipefail

# ── Dry-run flag ──────────────────────────────────────────────────────────────
DRY_RUN=false
for arg in "$@"; do
    [ "${arg}" = "--dry-run" ] && DRY_RUN=true
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${REPO_ROOT}/backups/preflight_${TIMESTAMP}"
MANIFEST_DIR="${REPO_ROOT}/backups/manifests"

# In dry-run mode we never write to disk — direct log to stdout only
if "${DRY_RUN}"; then
    LOG_FILE="/dev/null"
    log()  { echo "[DRY-RUN $(date +%T)] $*"; }
    run()  { echo "[DRY-RUN] WOULD RUN: $*"; }
    fail() { echo "[DRY-RUN FAIL] $*"; exit 1; }
else
    mkdir -p "${BACKUP_DIR}" "${MANIFEST_DIR}"
    LOG_FILE="${BACKUP_DIR}/backup.log"
    log()  { echo "[$(date +%T)] $*" | tee -a "${LOG_FILE}"; }
    run()  { "$@"; }
    fail() { echo "[$(date +%T)] FAIL: $*" | tee -a "${LOG_FILE}"; exit 1; }
fi

cd "${REPO_ROOT}"

# Load .env values safely (no subshell env pollution)
_env_val() { grep -E "^${1}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'" || true; }

POSTGRES_USER="$(_env_val POSTGRES_USER)"
POSTGRES_DB="$(_env_val POSTGRES_DB)"
POSTGRES_PASSWORD="$(_env_val POSTGRES_PASSWORD)"

[ -z "${POSTGRES_USER}" ] && fail "POSTGRES_USER not found in .env"
[ -z "${POSTGRES_DB}" ]   && fail "POSTGRES_DB not found in .env"

log "================================================================="
"${DRY_RUN}" && log "*** DRY RUN — no files will be written, no commands executed ***"
log "Amber2 Preflight Backup — ${TIMESTAMP}"
log "Repo root:      ${REPO_ROOT}"
log "Backup dir:     ${BACKUP_DIR}"
log "Manifest dir:   ${MANIFEST_DIR}"
log "================================================================="

# ── Preflight checks ──────────────────────────────────────────────────────────
log ""
log "--- Preflight checks"

AVAIL_KB=$(df -k "${REPO_ROOT}" | awk 'NR==2 {print $4}')
AVAIL_GB=$(( AVAIL_KB / 1024 / 1024 ))
log "Available disk space: ${AVAIL_GB}GB"
if ! "${DRY_RUN}"; then
    [ "${AVAIL_GB}" -lt 20 ] && fail "Less than 20GB free — aborting to protect production data."
else
    [ "${AVAIL_GB}" -lt 20 ] && log "  WARNING: Less than 20GB free — real run would abort here."
fi

log "Checking required tools..."
for tool in docker tar gzip curl; do
    if command -v "${tool}" &>/dev/null; then
        log "  ${tool}: $(command -v "${tool}") — OK"
    else
        log "  ${tool}: NOT FOUND — real run would fail"
    fi
done

log "Checking containers..."
for container in amber2-api-1 amber2-worker-1 amber2-postgres-1 amber2-redis-1 \
                 amber2-neo4j-1 amber2-milvus-1 amber2-etcd-1 amber2-garage-1; do
    STATUS=$(docker inspect --format '{{.State.Status}}' "${container}" 2>/dev/null || echo "missing")
    if [ "${STATUS}" = "running" ]; then
        log "  ${container}: running — OK"
    else
        log "  ${container}: ${STATUS} — PROBLEM (real run would abort)"
        "${DRY_RUN}" || fail "Container ${container} is not running (status: ${STATUS}). Abort."
    fi
done

log "Checking volume host paths exist..."
for vol in amber2_graphrag-postgres amber2_graphrag-neo4j amber2_graphrag-etcd \
           amber2_graphrag-milvus amber2_graphrag-garage-data amber2_graphrag-garage-meta \
           amber2_graphrag-redis amber2_graphrag-uploads; do
    VOL_PATH="/var/lib/docker/volumes/${vol}/_data"
    if [ -d "${VOL_PATH}" ]; then
        SIZE=$(du -sh "${VOL_PATH}" 2>/dev/null | cut -f1)
        log "  ${vol}: ${VOL_PATH} — ${SIZE}"
    else
        log "  ${vol}: PATH NOT FOUND at ${VOL_PATH} — PROBLEM"
    fi
done

log "Checking config files..."
for f in .env docker-compose.yml docker/garage/garage.toml; do
    [ -f "${REPO_ROOT}/${f}" ] \
        && log "  ${f}: present — OK" \
        || log "  ${f}: MISSING"
done

# ── Step 1: Git state ─────────────────────────────────────────────────────────
log ""
log "--- Step 1: Git state"
log "  Would write: ${MANIFEST_DIR}/${TIMESTAMP}-git.txt"
log "  Current commit: $(git rev-parse HEAD)"
log "  Last 5 commits:"
git log --oneline -5 | while IFS= read -r line; do log "    ${line}"; done
GIT_DIRTY=$(git status --short | wc -l | tr -d ' ')
log "  Dirty files: ${GIT_DIRTY}"
if ! "${DRY_RUN}"; then
    GIT_FILE="${MANIFEST_DIR}/${TIMESTAMP}-git.txt"
    { echo "=== commit ==="; git rev-parse HEAD; echo ""; echo "=== log (last 5) ==="; git log --oneline -5; echo ""; echo "=== status ==="; git status --short || true; } > "${GIT_FILE}"
    log "  Written: ${GIT_FILE}"
fi

# ── Step 2: Container and image manifest ──────────────────────────────────────
log ""
log "--- Step 2: Container and image manifest"
log "  Would write:"
log "    ${MANIFEST_DIR}/${TIMESTAMP}-containers.txt"
log "    ${MANIFEST_DIR}/${TIMESTAMP}-images.txt"
log "  Custom images found:"
docker images --format '  {{.Repository}}:{{.Tag}}  id={{.ID}}  size={{.Size}}  created={{.CreatedAt}}' \
    | grep -E 'amber2' || log "  (none found)"
log "  Image tarballs (~3GB): NOT saved by default. Run separately if needed:"
log "    docker save amber2-api amber2-worker amber2-frontend | gzip > <backup_dir>/custom_images.tar.gz"
if ! "${DRY_RUN}"; then
    CONTAINERS_FILE="${MANIFEST_DIR}/${TIMESTAMP}-containers.txt"
    IMAGES_FILE="${MANIFEST_DIR}/${TIMESTAMP}-images.txt"
    { echo "=== docker compose ps ==="; docker compose ps 2>/dev/null; echo ""; echo "=== docker inspect ==="; docker inspect --format '{{.Name}}  image={{.Config.Image}}  sha={{.Image}}' amber2-api-1 amber2-worker-1 amber2-frontend-1 amber2-postgres-1 amber2-redis-1 amber2-neo4j-1 amber2-milvus-1 amber2-etcd-1 amber2-garage-1 2>/dev/null; } > "${CONTAINERS_FILE}"
    { echo "=== custom images ==="; docker images --format '{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}\t{{.Size}}' | grep -E '^amber2' || true; echo ""; echo "=== digests ==="; for img in amber2-api amber2-worker amber2-frontend; do DIGEST=$(docker inspect --format '{{.Id}}' "${img}:latest" 2>/dev/null || echo "not-found"); echo "${img}:latest  ${DIGEST}"; done; } > "${IMAGES_FILE}"
    log "  Written: ${CONTAINERS_FILE}"
    log "  Written: ${IMAGES_FILE}"
fi

# ── Step 3: Volume inventory ──────────────────────────────────────────────────
log ""
log "--- Step 3: Volume inventory"
log "  Would write: ${MANIFEST_DIR}/${TIMESTAMP}-volumes.txt"
log "  Volumes:"
docker volume ls --filter name=amber2 | while IFS= read -r line; do log "    ${line}"; done
if ! "${DRY_RUN}"; then
    VOLUMES_FILE="${MANIFEST_DIR}/${TIMESTAMP}-volumes.txt"
    { docker volume ls --filter name=amber2; echo ""; docker volume inspect amber2_graphrag-postgres amber2_graphrag-neo4j amber2_graphrag-etcd amber2_graphrag-milvus amber2_graphrag-garage-data amber2_graphrag-garage-meta amber2_graphrag-redis amber2_graphrag-uploads amber2_pip-packages 2>/dev/null; } > "${VOLUMES_FILE}"
    log "  Written: ${VOLUMES_FILE}"
fi

# ── Step 4: Config snapshots ──────────────────────────────────────────────────
log ""
log "--- Step 4: Config snapshots"
log "  Would copy to: ${BACKUP_DIR}/config/"
log "    .env → env.snapshot"
log "    docker-compose.yml → docker-compose.yml.snapshot"
[ -f docker-compose.gpu.yml ]       && log "    docker-compose.gpu.yml"
[ -f docker/garage/garage.toml ]    && log "    docker/garage/garage.toml → garage.toml.snapshot"
if ! "${DRY_RUN}"; then
    CONFIG_DIR="${BACKUP_DIR}/config"
    mkdir -p "${CONFIG_DIR}"
    cp .env "${CONFIG_DIR}/env.snapshot"
    cp docker-compose.yml "${CONFIG_DIR}/docker-compose.yml.snapshot"
    [ -f docker-compose.gpu.yml ] && cp docker-compose.gpu.yml "${CONFIG_DIR}/"
    [ -f docker/garage/garage.toml ] && cp docker/garage/garage.toml "${CONFIG_DIR}/garage.toml.snapshot"
    log "  Written: ${CONFIG_DIR}"
fi

# ── Step 5: PostgreSQL online dump ────────────────────────────────────────────
log ""
log "--- Step 5: PostgreSQL dump (online)"
log "  Command: PGPASSWORD=*** docker compose exec -T postgres pg_dump -U ${POSTGRES_USER} ${POSTGRES_DB} | gzip"
log "  Output:  ${BACKUP_DIR}/postgres_${TIMESTAMP}.sql.gz"
log "  Impact:  online, read-only, zero service disruption"
if ! "${DRY_RUN}"; then
    PG_FILE="${BACKUP_DIR}/postgres_${TIMESTAMP}.sql.gz"
    PGPASSWORD="${POSTGRES_PASSWORD}" docker compose exec -T postgres \
        pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" \
        | gzip > "${PG_FILE}"
    log "  Written: ${PG_FILE} ($(du -sh "${PG_FILE}" | cut -f1))"
fi

# ── Step 6: Redis snapshot ────────────────────────────────────────────────────
log ""
log "--- Step 6: Redis snapshot"
log "  Command: redis-cli BGSAVE (async, non-blocking) then docker cp /data/dump.rdb"
log "  Output:  ${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
log "  Impact:  BGSAVE forks in background — no client impact"
REDIS_SIZE=$(docker exec amber2-redis-1 redis-cli INFO memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '[:space:]' || echo "unknown")
log "  Redis used_memory: ${REDIS_SIZE}"
if ! "${DRY_RUN}"; then
    docker exec amber2-redis-1 redis-cli BGSAVE > /dev/null
    log "  Redis BGSAVE triggered, waiting (max 60s)..."
    for i in $(seq 1 60); do
        IN_PROGRESS=$(docker exec amber2-redis-1 redis-cli INFO persistence \
            | grep rdb_bgsave_in_progress | tr -d '[:space:]' | cut -d: -f2)
        [ "${IN_PROGRESS}" = "0" ] && break
        sleep 1
    done
    REDIS_FILE="${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
    docker cp amber2-redis-1:/data/dump.rdb "${REDIS_FILE}"
    log "  Written: ${REDIS_FILE} ($(du -sh "${REDIS_FILE}" | cut -f1))"
fi

# ── Step 7: Neo4j volume snapshot ─────────────────────────────────────────────
log ""
log "--- Step 7: Neo4j volume snapshot (crash-consistent)"
log "  Command: tar -czf ... -C /var/lib/docker/volumes/amber2_graphrag-neo4j/_data ."
log "  Output:  ${BACKUP_DIR}/neo4j_volume_${TIMESTAMP}.tar.gz"
log "  Impact:  reads volume files while Neo4j is running — crash-consistent only"
log "  NOTE:    Neo4j Community has no online logical backup. For full consistency,"
log "           stop neo4j first and run: docker exec amber2-neo4j-1 neo4j-admin database dump"
NEO4J_VOL_SIZE=$(du -sh /var/lib/docker/volumes/amber2_graphrag-neo4j/_data 2>/dev/null | cut -f1 || echo "unknown")
log "  Volume size (uncompressed): ${NEO4J_VOL_SIZE}"
if ! "${DRY_RUN}"; then
    NEO4J_FILE="${BACKUP_DIR}/neo4j_volume_${TIMESTAMP}.tar.gz"
    tar -czf "${NEO4J_FILE}" -C /var/lib/docker/volumes/amber2_graphrag-neo4j/_data \
        --warning=no-file-changed . 2>>"${LOG_FILE}" || true
    log "  Written: ${NEO4J_FILE} ($(du -sh "${NEO4J_FILE}" | cut -f1))"
fi

# ── Step 8: Milvus and etcd volume snapshots ──────────────────────────────────
log ""
log "--- Step 8: Milvus and etcd volume snapshots (crash-consistent)"
for vol in milvus etcd; do
    VOL_PATH="/var/lib/docker/volumes/amber2_graphrag-${vol}/_data"
    VOL_SIZE=$(du -sh "${VOL_PATH}" 2>/dev/null | cut -f1 || echo "unknown")
    log "  ${vol} volume size (uncompressed): ${VOL_SIZE}"
    log "  Output: ${BACKUP_DIR}/${vol}_volume_${TIMESTAMP}.tar.gz"
done
log "  Impact: reads volume files while services are running — crash-consistent only"
if ! "${DRY_RUN}"; then
    for vol in milvus etcd; do
        OUT="${BACKUP_DIR}/${vol}_volume_${TIMESTAMP}.tar.gz"
        tar -czf "${OUT}" -C "/var/lib/docker/volumes/amber2_graphrag-${vol}/_data" \
            --warning=no-file-changed . 2>>"${LOG_FILE}" || true
        log "  Written: ${OUT} ($(du -sh "${OUT}" | cut -f1))"
    done
fi

# ── Step 9: Garage object storage volume snapshots ────────────────────────────
log ""
log "--- Step 9: Garage object storage volume snapshots (crash-consistent)"
log "  Garage uses SQLite backend — volume snapshot captures full object data and metadata"
for vol in garage-data garage-meta; do
    VOL_PATH="/var/lib/docker/volumes/amber2_graphrag-${vol}/_data"
    VOL_SIZE=$(du -sh "${VOL_PATH}" 2>/dev/null | cut -f1 || echo "unknown")
    log "  ${vol} size (uncompressed): ${VOL_SIZE}"
    log "  Output: ${BACKUP_DIR}/${vol}_volume_${TIMESTAMP}.tar.gz"
done
log "  Garage buckets (read-only check):"
docker exec amber2-garage-1 /garage bucket list 2>/dev/null \
    | while IFS= read -r line; do log "    ${line}"; done \
    || log "    WARNING: could not list buckets"
if ! "${DRY_RUN}"; then
    for vol in garage-data garage-meta; do
        OUT="${BACKUP_DIR}/${vol}_volume_${TIMESTAMP}.tar.gz"
        tar -czf "${OUT}" -C "/var/lib/docker/volumes/amber2_graphrag-${vol}/_data" \
            --warning=no-file-changed . 2>>"${LOG_FILE}" || true
        log "  Written: ${OUT} ($(du -sh "${OUT}" | cut -f1))"
    done
fi

# ── Step 10: Uploads volume snapshot ──────────────────────────────────────────
log ""
log "--- Step 10: Uploads volume snapshot"
UPLOADS_SIZE=$(du -sh /var/lib/docker/volumes/amber2_graphrag-uploads/_data 2>/dev/null | cut -f1 || echo "unknown")
log "  Uploads volume size (uncompressed): ${UPLOADS_SIZE}"
log "  Output: ${BACKUP_DIR}/uploads_volume_${TIMESTAMP}.tar.gz"
if ! "${DRY_RUN}"; then
    UPLOADS_FILE="${BACKUP_DIR}/uploads_volume_${TIMESTAMP}.tar.gz"
    tar -czf "${UPLOADS_FILE}" -C /var/lib/docker/volumes/amber2_graphrag-uploads/_data \
        --warning=no-file-changed . 2>>"${LOG_FILE}" || true
    log "  Written: ${UPLOADS_FILE} ($(du -sh "${UPLOADS_FILE}" | cut -f1))"
fi

# ── Step 11: Live health evidence ─────────────────────────────────────────────
log ""
log "--- Step 11: Live health evidence"
log "  Would write: ${MANIFEST_DIR}/${TIMESTAMP}-health.txt"
log "  Checks: docker compose ps, container health states, /health, /health/ready, frontend"
log "  Current health snapshot:"
docker inspect \
    --format '  {{.Name}}  status={{.State.Status}}  health={{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' \
    amber2-api-1 amber2-worker-1 amber2-frontend-1 \
    amber2-postgres-1 amber2-redis-1 amber2-neo4j-1 \
    amber2-milvus-1 amber2-etcd-1 amber2-garage-1 2>/dev/null \
    | while IFS= read -r line; do log "${line}"; done
log "  /health:       $(curl -sf http://127.0.0.1:8000/health 2>/dev/null | head -c 120 || echo 'FAIL')"
log "  /health/ready: $(curl -sf http://127.0.0.1:8000/health/ready 2>/dev/null | head -c 120 || echo 'FAIL')"
log "  frontend:      $(curl -Is http://127.0.0.1:3000/ 2>/dev/null | head -1 || echo 'FAIL')"
if ! "${DRY_RUN}"; then
    HEALTH_FILE="${MANIFEST_DIR}/${TIMESTAMP}-health.txt"
    { echo "=== timestamp ==="; date -u; echo ""; echo "=== docker compose ps ==="; docker compose ps 2>/dev/null; echo ""; echo "=== container health states ==="; docker inspect --format '{{.Name}}  status={{.State.Status}}  health={{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' amber2-api-1 amber2-worker-1 amber2-frontend-1 amber2-postgres-1 amber2-redis-1 amber2-neo4j-1 amber2-milvus-1 amber2-etcd-1 amber2-garage-1 2>/dev/null; echo ""; echo "=== api health ==="; curl -sf http://127.0.0.1:8000/health 2>/dev/null || echo "FAIL: /health"; echo ""; curl -sf http://127.0.0.1:8000/health/ready 2>/dev/null || echo "FAIL: /health/ready"; echo ""; echo "=== frontend ==="; curl -Is http://127.0.0.1:3000/ 2>/dev/null | head -3 || echo "FAIL: frontend"; } > "${HEALTH_FILE}"
    log "  Written: ${HEALTH_FILE}"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "================================================================="
if "${DRY_RUN}"; then
    log "DRY RUN complete — no files written, no commands executed"
    log "If everything above looks correct, run without --dry-run to execute"
else
    log "Backup complete — ${TIMESTAMP}"
    log "Artifacts:"
    ls -lh "${BACKUP_DIR}/" | tee -a "${LOG_FILE}"
    log ""
    TOTAL=$(du -sh "${BACKUP_DIR}" | cut -f1)
    log "Total backup size: ${TOTAL}"
    log ""
    log "Manifest files:"
    ls -lh "${MANIFEST_DIR}"/*"${TIMESTAMP}"* 2>/dev/null | tee -a "${LOG_FILE}" || true
    log ""
    log "Next step: run scripts/restore_preflight_check.sh to verify restoreability"
    log "Do not start Task 1 until restore drill passes."
fi
log "================================================================="
