#!/usr/bin/env bash
# restore.sh — restore an Amber backup into a docker compose project.
#
# Two uses, same code path:
#   1. Restore drill into a throwaway mirror project (default --project=ambermirror).
#      This is the ONLY way to prove a backup is restorable. Run it before every
#      migration or risky deploy.
#   2. Seed a fresh host (--project=amber2 --repo=/root/amber2), which is the
#      migration itself.
#
# Creates volumes under ${PROJECT}_graphrag-*, so a mirror never touches the
# volumes of another project on the same daemon. Uses the prod .env snapshot from
# the backup so Postgres roles and the Neo4j password match the dumps.
#
# ponytail: the mirror reuses prod ports (5433/7474/7687/9001/19530/6379/80).
# Run ONE stack at a time — stop the other project before `up`-ing this one.
# If you need both simultaneously, remap ports in a compose override; skipped
# until you actually need concurrent stacks.
#
# Usage:
#   bash scripts/restore.sh --backup=/opt/backups/amber/backup_XXXX --dry-run
#   bash scripts/restore.sh --backup=/opt/backups/amber/backup_XXXX
#   bash scripts/restore.sh --backup=... --project=amber2 --repo=/root/amber2
#
# See docs/MIGRATION_RUNBOOK.md for the procedure this script belongs to.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=false
BACKUP_DIR=""
PROJECT="ambermirror"
# Default to the repo this script ships in, so a checkout is self-contained.
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WITH_APP=false
SKIP_VERIFY=false

for arg in "$@"; do
    case "$arg" in
        --dry-run)      DRY_RUN=true ;;
        --backup=*)     BACKUP_DIR="${arg#*=}" ;;
        --project=*)    PROJECT="${arg#*=}" ;;
        --repo=*)       REPO_ROOT="${arg#*=}" ;;
        --with-app)     WITH_APP=true ;;   # also start api/worker/nginx (prod .env → may do outbound calls!)
        --skip-verify)  SKIP_VERIFY=true ;;
        -h|--help)      sed -n '2,26p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 1 ;;
    esac
done

[ -n "$BACKUP_DIR" ] || { echo "FAIL: --backup=<dir> required" >&2; exit 1; }
[ -d "$BACKUP_DIR" ] || { echo "FAIL: backup dir not found: $BACKUP_DIR" >&2; exit 1; }
[ -f "$REPO_ROOT/docker-compose.yml" ] || { echo "FAIL: no docker-compose.yml in $REPO_ROOT" >&2; exit 1; }

# Artifact gate. verify_backup.sh is read-only and covers the FAILED marker,
# checksums, the Neo4j dump form, the Postgres TOC and the etcd snapshot — all
# the ways this restore can silently produce an empty or partial stack.
if $SKIP_VERIFY; then
    echo "WARN: --skip-verify — restoring artifacts that were never checked" >&2
else
    bash "${SCRIPT_DIR}/verify_backup.sh" --backup="$BACKUP_DIR" \
        || { echo "FAIL: backup did not pass verification — refusing to restore from it" >&2; exit 1; }
fi

ENV_SNAPSHOT="$BACKUP_DIR/config/.env.snapshot"
[ -f "$ENV_SNAPSHOT" ] || { echo "FAIL: prod .env snapshot missing: $ENV_SNAPSHOT" >&2; exit 1; }

# Load creds (Postgres user/db, Neo4j password) from the prod snapshot,
# then scrub any var that could redirect docker at the wrong daemon/project.
set -a; # shellcheck disable=SC1090
source "$ENV_SNAPSHOT"; set +a
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_PROFILES 2>/dev/null || true
: "${POSTGRES_USER:=graphrag}"
: "${POSTGRES_DB:=graphrag}"
: "${NEO4J_USER:=neo4j}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD missing in .env snapshot}"

say() { echo "[$(date +%T)] $*"; }
run() { if $DRY_RUN; then echo "  WOULD RUN: $*"; else "$@"; fi; }
dc()  { docker compose -p "$PROJECT" --env-file "$ENV_SNAPSHOT" -f "$REPO_ROOT/docker-compose.yml" "$@"; }

say "Backup:   $BACKUP_DIR"
say "Project:  $PROJECT  (volumes ${PROJECT}_graphrag-*)"
say "Repo:     $REPO_ROOT"
say "Dry run:  $DRY_RUN"

# Guard: refuse to clobber pre-existing volumes unless dry-run. On a migration
# this is what stops a second run from restoring on top of a live dataset.
existing=$(docker volume ls -q | grep -E "^${PROJECT}_graphrag-" || true)
if [ -n "$existing" ] && ! $DRY_RUN; then
    echo "FAIL: volumes for project '${PROJECT}' already exist — remove them first or pick another --project:" >&2
    echo "$existing" >&2
    echo "  docker compose -p $PROJECT down -v   # DESTROYS this project's data" >&2
    exit 1
fi

# Preflight: prove compose resolves EVERY volume/container under the project
# prefix — never into another project's volumes. Abort if any declared volume is
# external or resolves outside ${PROJECT}_.
resolved=$(dc config --format json 2>/dev/null | tr ',' '\n' | grep -oE '"name":[[:space:]]*"[^"]*graphrag-[^"]*"' | grep -oE '[a-zA-Z0-9_-]*graphrag-[a-zA-Z0-9_-]*' || true)
bad=$(echo "$resolved" | grep -vE "^${PROJECT}_" | grep -E "graphrag-" || true)
if [ -n "$bad" ]; then
    echo "FAIL: compose resolves volumes OUTSIDE ${PROJECT}_ — refusing (would touch other projects' volumes):" >&2
    echo "$bad" >&2
    exit 1
fi
say "Volume isolation OK — all graphrag volumes resolve under ${PROJECT}_"

# Restore a gzip'd volume tar into a named docker volume via ephemeral alpine.
restore_volume() {
    local tarfile="$1" vol="${PROJECT}_$2"
    if [ ! -f "$tarfile" ]; then say "  skip (no $tarfile)"; return; fi
    say "  volume $vol  <-  $(basename "$tarfile")"
    run docker run --rm \
        -v "${vol}:/dst" \
        -v "${BACKUP_DIR}:/src:ro" \
        alpine sh -c "cd /dst && tar xzf /src/$(basename "$tarfile")"
}

# ── 1) Volume-based stores: inject BEFORE first container start ───────────────
say ""
say "--- [1] Volume restores (milvus + etcd + minio + redis + uploads)"
restore_volume "$BACKUP_DIR/milvus.tar.gz"     graphrag-milvus
restore_volume "$BACKUP_DIR/etcd.tar.gz"       graphrag-etcd     # only if backup tarred it
restore_volume "$BACKUP_DIR/minio-data.tar.gz" graphrag-minio-data
restore_volume "$BACKUP_DIR/redis.tar.gz"      graphrag-redis
restore_volume "$BACKUP_DIR/uploads.tar.gz"    graphrag-uploads

# etcd came as a raw snapshot (etcd.snap), not a volume tar → restore into the
# etcd data volume by replaying the snapshot inside an etcd image.
if [ -f "$BACKUP_DIR/etcd.snap" ] && [ ! -f "$BACKUP_DIR/etcd.tar.gz" ]; then
    say "  etcd snapshot -> ${PROJECT}_graphrag-etcd (etcdctl snapshot restore)"
    run docker run --rm \
        -v "${PROJECT}_graphrag-etcd:/etcd" \
        -v "${BACKUP_DIR}:/src:ro" \
        -e ETCDCTL_API=3 \
        quay.io/coreos/etcd:v3.5.5 sh -c \
        "etcdctl snapshot restore /src/etcd.snap --data-dir=/etcd/restored && rm -rf /etcd/member && mv /etcd/restored/member /etcd/member && rm -rf /etcd/restored"
fi

# ── 2) Neo4j — cypher replay (APOC) OR volume tar (fallback) ──────────────────
say ""
say "--- [2] Neo4j"
NEO4J_MODE=""
if [ -f "$BACKUP_DIR/neo4j.tar.gz" ]; then
    NEO4J_MODE="volume"
    restore_volume "$BACKUP_DIR/neo4j.tar.gz" graphrag-neo4j
elif [ -f "$BACKUP_DIR/neo4j.cypher" ]; then
    NEO4J_MODE="cypher"
    say "  APOC cypher export present → will replay after neo4j starts"
else
    say "  WARN: no neo4j artifact found in backup"
fi

# ── 3) Start datastores (Postgres starts EMPTY for logical restore) ───────────
say ""
say "--- [3] Start datastore containers"
run dc up -d postgres neo4j redis etcd minio milvus

say "  waiting for postgres to accept connections..."
if ! $DRY_RUN; then
    for _ in $(seq 1 60); do
        if dc exec -T postgres pg_isready -U "$POSTGRES_USER" >/dev/null 2>&1; then break; fi
        sleep 2
    done
fi

# ── 4) Postgres logical restore ───────────────────────────────────────────────
# The DB-only pg_dump carries GRANTs to the non-owner RLS role `graphrag_app`
# but NOT the role itself (roles are cluster-global). Prod creates it via alembic
# migration 20260325_1600_db_role_and_rls_hardening. Recreate it here first, with
# the SAME password from the prod .env snapshot, so GRANTs land and RLS matches prod.
# ponytail: single-quote password interpolation; a pw containing a "'" would break
# it — none do here. Fix with psql -v if that ever changes.
say ""
say "--- [4a] Ensure graphrag_app RLS role exists"
if [ -n "${GRAPHRAG_APP_PASSWORD:-}" ]; then
    if $DRY_RUN; then
        echo "  WOULD RUN: psql CREATE ROLE graphrag_app WITH LOGIN NOSUPERUSER ... (password from snapshot)"
    else
        printf "CREATE ROLE graphrag_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '%s';\n" "$GRAPHRAG_APP_PASSWORD" \
            | dc exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" 2>&1 | grep -v "already exists" || true
    fi
else
    say "  WARN: GRAPHRAG_APP_PASSWORD missing from snapshot — GRANTs to graphrag_app will fail"
fi

say ""
say "--- [4b] Postgres restore (pg_restore from postgres.dump)"
if [ -f "$BACKUP_DIR/postgres.dump" ]; then
    # --clean --if-exists makes it re-runnable. graphrag_app created in 4a above.
    run bash -c "docker compose -p '$PROJECT' --env-file '$ENV_SNAPSHOT' -f '$REPO_ROOT/docker-compose.yml' exec -T postgres pg_restore --clean --if-exists --no-owner -U '$POSTGRES_USER' -d '$POSTGRES_DB' < '$BACKUP_DIR/postgres.dump' || true"
else
    say "  WARN: postgres.dump missing"
fi

# ── 5) Neo4j cypher replay (only in cypher mode) ──────────────────────────────
if [ "$NEO4J_MODE" = "cypher" ]; then
    say ""
    say "--- [5] Neo4j cypher replay"
    say "  waiting for neo4j bolt..."
    if ! $DRY_RUN; then
        for _ in $(seq 1 60); do
            if dc exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" "RETURN 1" >/dev/null 2>&1; then break; fi
            sleep 2
        done
    fi
    run bash -c "docker compose -p '$PROJECT' --env-file '$ENV_SNAPSHOT' -f '$REPO_ROOT/docker-compose.yml' exec -T neo4j cypher-shell -u '$NEO4J_USER' -p '$NEO4J_PASSWORD' < '$BACKUP_DIR/neo4j.cypher'"
fi

# ── 6) Optionally bring up the app ────────────────────────────────────────────
# Default: datastores only. The app (esp. worker/celery_beat) runs with the PROD
# .env → connectors/webhooks could make real outbound calls with prod creds, and
# on a mirror the worker's boot recovery sweep would rewrite document statuses.
# Pass --with-app only once you've sanitized outbound side effects.
if $WITH_APP; then
    say ""
    say "--- [6] Start app services (--with-app)"
    say "  WARN: worker/beat use prod .env — may trigger outbound calls with prod creds"
    run dc up -d
else
    say ""
    say "--- [6] App NOT started (datastores only). Re-run with --with-app to start api/worker/nginx."
fi

say ""
say "============================================================"
say "Restore complete (project=$PROJECT)."
say "  Postgres: localhost:5433   Neo4j: :7474/:7687   Milvus: :19530   App: :80"
say "  Stop:  docker compose -p $PROJECT down"
say "  Wipe:  docker compose -p $PROJECT down -v      # DESTROYS this project's data"
say "============================================================"
say "Next: run the post-restore parity checks in docs/MIGRATION_RUNBOOK.md, step 3."
