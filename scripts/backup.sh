#!/usr/bin/env bash
# backup.sh — Amber2 production backup.
#
# Stack: MinIO object storage, amber2-* container names, Postgres roles from
# .env, etcd snapshot, Redis BGSAVE.
#
# SAFE TO RUN ON PRODUCTION: does not stop or restart containers.
# All captures are online (pg_dump, BGSAVE, etcdctl snapshot) or crash-
# consistent volume tars while the service keeps running.
#
# Usage:
#   bash scripts/backup.sh                      # real run, default destination
#   bash scripts/backup.sh --dry-run            # print plan, write nothing
#   bash scripts/backup.sh --destination=/opt/backups/amber --retention=7
#   bash scripts/backup.sh --skip=milvus,uploads
#   bash scripts/backup.sh --include=postgres,neo4j,minio
#
# Run from anywhere; resolves repo root relative to this script.

set -euo pipefail
IFS=$'\n\t'

# ── Defaults ──────────────────────────────────────────────────────────────────
DRY_RUN=false
DESTINATION="/opt/backups/amber"
RETENTION=7
SKIP_COMPONENTS=""
INCLUDE_COMPONENTS=""
MIN_FREE_GB=10

usage() {
    sed -n '2,25p' "$0"
    exit "${1:-0}"
}

# ── Arg parsing ───────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --dry-run)            DRY_RUN=true ;;
        --destination=*)      DESTINATION="${arg#*=}" ;;
        --retention=*)        RETENTION="${arg#*=}" ;;
        --skip=*)             SKIP_COMPONENTS="${arg#*=}" ;;
        --include=*)          INCLUDE_COMPONENTS="${arg#*=}" ;;
        -h|--help)            usage 0 ;;
        *)                    echo "Unknown arg: $arg"; usage 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${DESTINATION}/backup_${TIMESTAMP}"
MANIFEST="${BACKUP_DIR}/MANIFEST.txt"

ALL_COMPONENTS=(postgres neo4j redis milvus etcd minio uploads config)

# ── Logging helpers (mirror backup_preflight.sh style) ────────────────────────
if "${DRY_RUN}"; then
    log()  { echo "[DRY-RUN $(date +%T)] $*"; }
    run()  { echo "[DRY-RUN] WOULD RUN: $*"; }
    fail() { echo "[DRY-RUN FAIL] $*" >&2; exit 1; }
else
    log()  { echo "[$(date +%T)] $*" | tee -a "${MANIFEST}" >/dev/null 2>&1 || echo "[$(date +%T)] $*"; }
    run()  { "$@"; }
    fail() {
        echo "[$(date +%T)] FAIL: $*" >&2
        touch "${BACKUP_DIR}/FAILED" 2>/dev/null || true
        exit 1
    }
fi

# Component selection helper.
want() {
    local c="$1"
    if [ -n "${INCLUDE_COMPONENTS}" ]; then
        [[ ",${INCLUDE_COMPONENTS}," == *",${c},"* ]]
        return
    fi
    [[ ",${SKIP_COMPONENTS}," != *",${c},"* ]]
}

# ── Preflight ─────────────────────────────────────────────────────────────────
log "============================================================"
log "Amber2 backup — ${TIMESTAMP}"
log "Repo root:    ${REPO_ROOT}"
log "Destination:  ${BACKUP_DIR}"
log "Retention:    ${RETENTION} (0 = keep all)"
log "Dry run:      ${DRY_RUN}"
log "============================================================"

# Check required tools.
for tool in docker tar gzip sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || fail "Missing required tool: $tool"
done

# Check free space on destination filesystem (on real run).
if ! "${DRY_RUN}"; then
    parent="${DESTINATION}"
    while [ ! -d "$parent" ] && [ "$parent" != "/" ]; do parent="$(dirname "$parent")"; done
    avail_gb=$(df -BG "$parent" | awk 'NR==2 { gsub("G","",$4); print $4 }')
    if [ "${avail_gb:-0}" -lt "${MIN_FREE_GB}" ]; then
        fail "Only ${avail_gb}GB free on $(df -h "$parent" | awk 'NR==2{print $6}'); need >= ${MIN_FREE_GB}GB"
    fi
    log "Available space on ${parent}: ${avail_gb}GB"
fi

# Check containers are running (required for logical dumps).
REQUIRED_CONTAINERS=(amber2-postgres-1 amber2-neo4j-1 amber2-redis-1 amber2-etcd-1 amber2-milvus-1 amber2-minio-1)
for c in "${REQUIRED_CONTAINERS[@]}"; do
    if docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -q true; then
        log "Container ${c}: running"
    else
        fail "Container ${c} is not running"
    fi
done

# Load .env for credentials (Neo4j password especially).
if [ -f "${REPO_ROOT}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
    log ".env loaded"
else
    fail ".env not found at ${REPO_ROOT}/.env"
fi

: "${POSTGRES_USER:=graphrag}"
: "${POSTGRES_DB:=graphrag}"
: "${NEO4J_USER:=neo4j}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD missing in .env}"

# Create backup directory (real run only).
if ! "${DRY_RUN}"; then
    mkdir -p "${BACKUP_DIR}"
    : > "${MANIFEST}"
    log "Created ${BACKUP_DIR}"
fi

# Helper: tar a named volume read-only via an ephemeral alpine container.
tar_volume() {
    local vol="$1" out="$2"
    log "  tar volume ${vol} → ${out}"
    run docker run --rm \
        -v "${vol}:/src:ro" \
        -v "${BACKUP_DIR}:/dst" \
        alpine sh -c "tar czf /dst/$(basename "$out") -C /src ."
}

# Helper: record checksum for a produced file.
checksum() {
    local f="$1"
    if ! "${DRY_RUN}" && [ -f "$f" ]; then
        (cd "$(dirname "$f")" && sha256sum "$(basename "$f")") >> "${BACKUP_DIR}/SHA256SUMS"
    fi
}

# ── Components ────────────────────────────────────────────────────────────────

# 1) Postgres — logical dump, custom format (compressed).
if want postgres; then
    log ""
    log "--- [1/8] Postgres"
    out="${BACKUP_DIR}/postgres.dump"
    if "${DRY_RUN}"; then
        log "  WOULD RUN: docker exec amber2-postgres-1 pg_dump -Fc -U ${POSTGRES_USER} ${POSTGRES_DB} > ${out}"
    else
        docker exec amber2-postgres-1 pg_dump -Fc -U "${POSTGRES_USER}" "${POSTGRES_DB}" > "${out}"
        checksum "${out}"
        log "  size: $(du -h "${out}" | cut -f1)"
    fi
fi

# 2) Neo4j — APOC cypher export to a FILE; falls back to volume tar if APOC refuses.
# NOTE: we export to a file inside the container (import dir) and copy it out.
# Do NOT use `stream:true ... RETURN cypherStatements` piped to a file — that goes
# through cypher-shell's result-cell rendering (header line, surrounding quotes,
# backslash-escaped inner quotes) and is NOT a replayable script. The file form
# produced by apoc.export.cypher.all(<file>, ...) is a clean cypher-shell script.
if want neo4j; then
    log ""
    log "--- [2/8] Neo4j"
    out="${BACKUP_DIR}/neo4j.cypher"
    container_file="/var/lib/neo4j/import/neo4j-backup.cypher"   # import dir per server.directories.import
    if "${DRY_RUN}"; then
        log "  WOULD RUN: docker exec amber2-neo4j-1 cypher-shell 'CALL apoc.export.cypher.all(\"neo4j-backup.cypher\", {...})'"
        log "  WOULD RUN: docker cp amber2-neo4j-1:${container_file} ${out}"
        log "  WOULD FALLBACK: tar_volume amber2_graphrag-neo4j ${out%.cypher}.tar.gz"
    else
        if docker exec amber2-neo4j-1 cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
            "CALL apoc.export.cypher.all('neo4j-backup.cypher', {format:'cypher-shell', useOptimizations:{type:'UNWIND_BATCH', unwindBatchSize:20}}) YIELD file RETURN file" \
            >/dev/null 2>&1 \
            && docker cp "amber2-neo4j-1:${container_file}" "${out}" >/dev/null 2>&1 \
            && [ -s "${out}" ]; then
            docker exec amber2-neo4j-1 rm -f "${container_file}" 2>/dev/null || true
            checksum "${out}"
            log "  APOC file export OK, size: $(du -h "${out}" | cut -f1)"
        else
            log "  APOC file export unavailable; falling back to volume tar"
            rm -f "${out}"
            docker exec amber2-neo4j-1 rm -f "${container_file}" 2>/dev/null || true
            tar_volume amber2_graphrag-neo4j "${BACKUP_DIR}/neo4j.tar.gz"
            checksum "${BACKUP_DIR}/neo4j.tar.gz"
        fi
    fi
fi

# 3) Redis — trigger BGSAVE, wait for completion, then volume tar.
if want redis; then
    log ""
    log "--- [3/8] Redis"
    if "${DRY_RUN}"; then
        log "  WOULD RUN: docker exec amber2-redis-1 redis-cli BGSAVE && wait LASTSAVE"
        log "  WOULD RUN: tar_volume amber2_graphrag-redis redis.tar.gz"
    else
        last_before=$(docker exec amber2-redis-1 redis-cli LASTSAVE)
        docker exec amber2-redis-1 redis-cli BGSAVE >/dev/null
        # Poll LASTSAVE for up to 60s.
        for _ in $(seq 1 60); do
            sleep 1
            last_after=$(docker exec amber2-redis-1 redis-cli LASTSAVE)
            [ "${last_after}" != "${last_before}" ] && break
        done
        tar_volume amber2_graphrag-redis "${BACKUP_DIR}/redis.tar.gz"
        checksum "${BACKUP_DIR}/redis.tar.gz"
    fi
fi

# 4) Milvus — volume tar (Milvus has no simple logical export for the whole cluster).
if want milvus; then
    log ""
    log "--- [4/8] Milvus"
    if "${DRY_RUN}"; then
        log "  WOULD RUN: tar_volume amber2_graphrag-milvus milvus.tar.gz"
    else
        tar_volume amber2_graphrag-milvus "${BACKUP_DIR}/milvus.tar.gz"
        checksum "${BACKUP_DIR}/milvus.tar.gz"
    fi
fi

# 5) Etcd — hot snapshot (preserves Milvus metadata coherency on restore).
if want etcd; then
    log ""
    log "--- [5/8] Etcd"
    snap="/tmp/etcd_${TIMESTAMP}.snap"
    if "${DRY_RUN}"; then
        log "  WOULD RUN: docker exec amber2-etcd-1 etcdctl snapshot save ${snap}"
    else
        docker exec amber2-etcd-1 etcdctl snapshot save "${snap}" >/dev/null
        docker cp "amber2-etcd-1:${snap}" "${BACKUP_DIR}/etcd.snap"
        docker exec amber2-etcd-1 rm -f "${snap}"
        checksum "${BACKUP_DIR}/etcd.snap"
        log "  size: $(du -h "${BACKUP_DIR}/etcd.snap" | cut -f1)"
    fi
fi

# 6) MinIO — tar the data volume.
if want minio; then
    log ""
    log "--- [6/8] MinIO"
    if "${DRY_RUN}"; then
        log "  WOULD RUN: tar_volume amber2_graphrag-minio-data minio-data.tar.gz"
    else
        tar_volume amber2_graphrag-minio-data "${BACKUP_DIR}/minio-data.tar.gz"
        checksum "${BACKUP_DIR}/minio-data.tar.gz"
    fi
fi

# 7) Uploads — legacy volume, retained for older document refs.
if want uploads; then
    log ""
    log "--- [7/8] Uploads"
    if "${DRY_RUN}"; then
        log "  WOULD RUN: tar_volume amber2_graphrag-uploads uploads.tar.gz"
    else
        tar_volume amber2_graphrag-uploads "${BACKUP_DIR}/uploads.tar.gz"
        checksum "${BACKUP_DIR}/uploads.tar.gz"
    fi
fi

# 8) Config snapshots and manifests.
if want config; then
    log ""
    log "--- [8/8] Config + manifests"
    if "${DRY_RUN}"; then
        log "  WOULD COPY: .env, docker-compose.yml, docker-compose.prod.yml, config/settings.yaml"
        log "  WOULD WRITE: git.txt, containers.txt, images.txt, volumes.txt"
    else
        mkdir -p "${BACKUP_DIR}/config"
        for f in .env docker-compose.yml docker-compose.prod.yml config/settings.yaml; do
            if [ -f "${REPO_ROOT}/${f}" ]; then
                cp "${REPO_ROOT}/${f}" "${BACKUP_DIR}/config/$(basename "$f").snapshot"
            fi
        done
        (cd "${REPO_ROOT}" && git rev-parse HEAD 2>/dev/null;  git status --short 2>/dev/null;  git log -5 --oneline 2>/dev/null) \
            > "${BACKUP_DIR}/git.txt" || true
        docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' > "${BACKUP_DIR}/containers.txt"
        docker image ls > "${BACKUP_DIR}/images.txt"
        docker volume ls > "${BACKUP_DIR}/volumes.txt"
    fi
fi

# ── Retention — delete old backups beyond RETENTION count ─────────────────────
if ! "${DRY_RUN}" && [ "${RETENTION}" -gt 0 ]; then
    log ""
    log "--- Retention (keep newest ${RETENTION})"
    count=$(find "${DESTINATION}" -maxdepth 1 -type d -name 'backup_*' | wc -l)
    if [ "${count}" -gt "${RETENTION}" ]; then
        find "${DESTINATION}" -maxdepth 1 -type d -name 'backup_*' -printf '%T@ %p\n' \
            | sort -n \
            | head -n $((count - RETENTION)) \
            | awk '{print $2}' \
            | while read -r d; do
                log "  deleting ${d}"
                rm -rf "${d}"
            done
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "============================================================"
if "${DRY_RUN}"; then
    log "DRY-RUN complete. No files written."
else
    total_size=$(du -sh "${BACKUP_DIR}" | cut -f1)
    log "Backup complete at ${BACKUP_DIR} (${total_size})"
fi
log "============================================================"
