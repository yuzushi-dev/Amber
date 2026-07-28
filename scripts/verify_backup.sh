#!/usr/bin/env bash
# verify_backup.sh — prove a backup directory is RESTORABLE before trusting it.
#
# READ-ONLY: never writes into the backup dir, never touches live containers or
# volumes. Safe to run on production while the stack serves traffic.
#
# Why this exists: backup.sh logs "APOC export OK" for a Neo4j dump that
# cypher-shell cannot replay (the pre-ffd4b1f3 `stream:true ... RETURN
# cypherStatements` form renders result cells: a `cypherStatements` header line
# and per-batch wrapping quotes). A backup that reports success and restores to
# nothing is worse than no backup, so every artifact gets checked for the
# property the restore actually depends on — not just for existence and size.
#
# Usage:
#   bash scripts/verify_backup.sh --backup=/opt/backups/amber/backup_YYYYmmdd_HHMMSS
#
# Exit status: 0 = no FAIL (WARNs may remain and must be read), 1 = at least
# one FAIL. Wire this into the migration runbook as a hard gate.

set -euo pipefail

BACKUP_DIR=""

for arg in "$@"; do
    case "$arg" in
        --backup=*) BACKUP_DIR="${arg#*=}" ;;
        -h|--help)  sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 1 ;;
    esac
done

[ -n "${BACKUP_DIR}" ] || { echo "FAIL: --backup=<dir> required" >&2; exit 1; }
[ -d "${BACKUP_DIR}" ] || { echo "FAIL: backup dir not found: ${BACKUP_DIR}" >&2; exit 1; }

FAILURES=0
WARNINGS=0

say()  { echo "[$(date +%T)] $*"; }
ok()   { echo "  OK    $*"; }
warn() { echo "  WARN  $*"; WARNINGS=$((WARNINGS + 1)); }
bad()  { echo "  FAIL  $*"; FAILURES=$((FAILURES + 1)); }

say "============================================================"
say "Amber backup verification"
say "Backup: ${BACKUP_DIR}"
say "============================================================"

# ── 1) Completeness markers ───────────────────────────────────────────────────
say ""
say "--- [1/7] Completeness"

if [ -f "${BACKUP_DIR}/FAILED" ]; then
    bad "FAILED marker present — backup.sh aborted partway; this snapshot is partial"
else
    ok "no FAILED marker"
fi

# A backup taken with --skip/--include is partial by construction, and retention
# counts it like any other, so a partial snapshot can evict a complete one.
# Detect it here rather than at restore time.
for f in postgres.dump config/.env.snapshot; do
    if [ -f "${BACKUP_DIR}/${f}" ]; then
        ok "present: ${f}"
    else
        bad "missing: ${f} (restore cannot proceed without it)"
    fi
done

if [ -f "${BACKUP_DIR}/neo4j.cypher" ] || [ -f "${BACKUP_DIR}/neo4j.tar.gz" ]; then
    ok "present: a Neo4j artifact"
else
    bad "missing: neither neo4j.cypher nor neo4j.tar.gz — the graph is not backed up"
fi

for f in milvus.tar.gz minio-data.tar.gz redis.tar.gz etcd.snap; do
    [ -f "${BACKUP_DIR}/${f}" ] && ok "present: ${f}" || warn "missing: ${f} (component skipped?)"
done

# ── 2) Checksums ──────────────────────────────────────────────────────────────
say ""
say "--- [2/7] Checksums"

if [ -f "${BACKUP_DIR}/SHA256SUMS" ]; then
    if ( cd "${BACKUP_DIR}" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); then
        ok "sha256sum -c passed ($(wc -l < "${BACKUP_DIR}/SHA256SUMS") entries)"
    else
        bad "checksum mismatch — corrupt or truncated artifact:"
        ( cd "${BACKUP_DIR}" && sha256sum -c SHA256SUMS 2>&1 | grep -v ': OK$' | sed 's/^/        /' ) || true
    fi
else
    warn "no SHA256SUMS — cannot detect a truncated copy"
fi

# ── 3) Neo4j dump replayability ───────────────────────────────────────────────
# The check that matters: a cypher-shell script starts at `:begin`. The broken
# stream form starts with the column name `cypherStatements`, then wraps each
# batch in double quotes, so the first statement arrives as `":begin`.
say ""
say "--- [3/7] Neo4j dump"

if [ -f "${BACKUP_DIR}/neo4j.cypher" ]; then
    first_line=$(head -1 "${BACKUP_DIR}/neo4j.cypher")
    if [ "${first_line}" = "cypherStatements" ]; then
        bad "neo4j.cypher is the cypher-shell RESULT-CELL rendering, not a replayable script"
        echo "        first line: 'cypherStatements' (a column header)"
        echo "        cause: apoc.export.cypher.all(null, {stream:true}) piped through cypher-shell"
        echo "        fix:   apply commit ffd4b1f3 to scripts/backup.sh and re-take the backup"
    elif [ "${first_line#\"}" != "${first_line}" ]; then
        bad "neo4j.cypher first line starts with a quote — result-cell wrapping, not replayable"
        echo "        first line: ${first_line:0:60}"
    elif [ "${first_line}" = ":begin" ]; then
        if grep -q '^:commit' "${BACKUP_DIR}/neo4j.cypher"; then
            ok "neo4j.cypher is a replayable cypher-shell script (:begin … :commit)"
        else
            bad "neo4j.cypher opens with :begin but has no :commit — export was truncated"
        fi
    else
        warn "neo4j.cypher first line is unexpected: ${first_line:0:60}"
    fi
elif [ -f "${BACKUP_DIR}/neo4j.tar.gz" ]; then
    # Volume-tar fallback: crash-consistent only. Acceptable for a mirror drill,
    # risky as the sole artifact for a host migration.
    if gzip -t "${BACKUP_DIR}/neo4j.tar.gz" 2>/dev/null; then
        warn "only the volume-tar fallback is present — crash-consistent, not a logical dump"
    else
        bad "neo4j.tar.gz is not a valid gzip stream"
    fi
fi

# ── 4) Postgres dump readability ──────────────────────────────────────────────
# pg_restore --list parses the whole custom-format TOC, so it fails on a
# truncated dump. Prefer a local pg_restore, fall back to any running Postgres
# container (read-only: we only list, never restore).
say ""
say "--- [4/7] Postgres dump"

pg_toc() {
    if command -v pg_restore >/dev/null 2>&1; then
        pg_restore --list "${BACKUP_DIR}/postgres.dump" 2>/dev/null
        return
    fi
    local c
    c=$(docker ps --filter 'name=postgres' --format '{{.Names}}' 2>/dev/null | head -1)
    [ -n "${c}" ] || return 1
    docker exec -i "${c}" pg_restore --list < "${BACKUP_DIR}/postgres.dump" 2>/dev/null
}

if [ -f "${BACKUP_DIR}/postgres.dump" ]; then
    if toc=$(pg_toc) && [ -n "${toc}" ]; then
        entries=$(echo "${toc}" | grep -c '^[0-9]' || true)
        ok "pg_restore --list parsed the TOC (${entries} entries)"
        # documents is the table the whole product hangs off; its absence means
        # the dump is for the wrong database, not just a partial one.
        if echo "${toc}" | grep -q 'TABLE DATA public documents'; then
            ok "TOC contains TABLE DATA public documents"
        else
            bad "TOC has no 'TABLE DATA public documents' — wrong database or schema-only dump"
        fi
    else
        warn "no pg_restore available (local or in a running container) — dump left unverified"
    fi
fi

# ── 5) Tar artifacts ──────────────────────────────────────────────────────────
say ""
say "--- [5/7] Volume tars"

for f in milvus.tar.gz minio-data.tar.gz redis.tar.gz uploads.tar.gz neo4j.tar.gz; do
    p="${BACKUP_DIR}/${f}"
    [ -f "${p}" ] || continue
    if ! gzip -t "${p}" 2>/dev/null; then
        bad "${f} is not a valid gzip stream"
        continue
    fi
    # An archive holding only './' restores an empty volume. Legitimate for the
    # legacy uploads volume, suspicious for anything else.
    n=$(tar tzf "${p}" 2>/dev/null | grep -vE '^\./?$' | head -1 || true)
    if [ -z "${n}" ]; then
        if [ "${f}" = "uploads.tar.gz" ]; then
            warn "${f} holds no files (legacy volume — expected empty once uploads live in MinIO)"
        else
            bad "${f} holds no files — restoring it yields an empty volume"
        fi
    else
        ok "${f} valid, non-empty"
    fi
done

# ── 6) etcd snapshot ──────────────────────────────────────────────────────────
# Milvus keeps its metadata in etcd and its segments in MinIO. A snapshot that
# fails `etcdutl snapshot status` means the vector metadata is unrecoverable
# even though milvus.tar.gz and minio-data.tar.gz look fine.
say ""
say "--- [6/7] etcd snapshot"

if [ -f "${BACKUP_DIR}/etcd.snap" ]; then
    if command -v docker >/dev/null 2>&1; then
        if out=$(docker run --rm -v "${BACKUP_DIR}:/src:ro" quay.io/coreos/etcd:v3.5.5 \
                    etcdutl snapshot status /src/etcd.snap 2>/dev/null); then
            ok "etcdutl snapshot status: ${out}"
        else
            bad "etcdutl could not read etcd.snap — Milvus metadata is not restorable"
        fi
    else
        warn "docker unavailable — etcd.snap left unverified"
    fi
fi

# ── 7) Env snapshot completeness ──────────────────────────────────────────────
# restore.sh sources this file for the Postgres role, the Neo4j password, and
# the graphrag_app RLS role password. A missing key does not fail the restore
# loudly — it silently produces a stack whose RLS GRANTs never landed.
say ""
say "--- [7/7] Env snapshot"

ENV_SNAPSHOT="${BACKUP_DIR}/config/.env.snapshot"
if [ -f "${ENV_SNAPSHOT}" ]; then
    for k in POSTGRES_USER POSTGRES_DB NEO4J_PASSWORD GRAPHRAG_APP_PASSWORD; do
        if grep -qE "^${k}=.+" "${ENV_SNAPSHOT}"; then
            ok "${k} present"
        elif [ "${k}" = "GRAPHRAG_APP_PASSWORD" ]; then
            bad "${k} missing — GRANTs to the graphrag_app RLS role will not land on restore"
        else
            bad "${k} missing — restore cannot authenticate"
        fi
    done
    # A stale DEFAULT_LLM_MODEL is not a restore problem, but it is the value the
    # new host inherits, and gemma3:27b answers 410 on every key.
    if grep -qE '^DEFAULT_LLM_MODEL=gemma3:27b' "${ENV_SNAPSHOT}"; then
        warn "DEFAULT_LLM_MODEL=gemma3:27b is retired upstream (410) — update it on the target host"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
say ""
say "============================================================"
if [ "${FAILURES}" -gt 0 ]; then
    say "VERDICT: NOT RESTORABLE — ${FAILURES} failure(s), ${WARNINGS} warning(s)"
    say "Do not migrate or cut over from this backup."
    say "============================================================"
    exit 1
fi
say "VERDICT: restorable — 0 failures, ${WARNINGS} warning(s)"
[ "${WARNINGS}" -gt 0 ] && say "Read every WARN above before relying on this backup."
say "Next: prove it end-to-end with a restore drill (docs/MIGRATION_RUNBOOK.md, step 3)."
say "============================================================"
