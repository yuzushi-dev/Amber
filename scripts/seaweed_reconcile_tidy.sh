#!/usr/bin/env bash
set -euo pipefail

MINIO_ENDPOINT="${MINIO_ENDPOINT:-localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ROOT_USER:-minioadmin}"
MINIO_SECRET_KEY="${MINIO_ROOT_PASSWORD:-minioadmin}"

SEAWEED_ENDPOINT="${SEAWEED_ENDPOINT:-localhost:8333}"
SEAWEED_ACCESS_KEY="${OBJECT_STORAGE_ACCESS_KEY:-minioadmin}"
SEAWEED_SECRET_KEY="${OBJECT_STORAGE_SECRET_KEY:-minioadmin}"

WORKDIR="${WORKDIR:-/tmp}"
TIDY_PREFIXES="${TIDY_PREFIXES:-probe-,compat-,compat-debug-,migration-smoke}"
AUTO_SYNC="false"
APPLY_TIDY="false"
KEEP_ARTIFACTS="false"

usage() {
  cat <<'EOF'
Run SeaweedFS reconciliation + tidy workflow.

Usage:
  bash scripts/seaweed_reconcile_tidy.sh [options]

Options:
  --minio-endpoint <host:port>      Source endpoint (default: localhost:9000)
  --minio-access <key>              Source access key
  --minio-secret <secret>           Source secret key
  --seaweed-endpoint <host:port>    Destination endpoint (default: localhost:8333)
  --seaweed-access <key>            Destination access key
  --seaweed-secret <secret>         Destination secret key
  --workdir <path>                  Temp artifact directory (default: /tmp)
  --tidy-prefixes <csv>             Bucket prefixes to prune
  --auto-sync                       If drift is found, run storage_sync.sh and re-compare
  --apply-tidy                      Delete matching tidy buckets (default is dry-run)
  --keep-artifacts                  Keep generated manifest/compare files
  -h, --help                        Show help

Examples:
  bash scripts/seaweed_reconcile_tidy.sh
  bash scripts/seaweed_reconcile_tidy.sh --apply-tidy
  bash scripts/seaweed_reconcile_tidy.sh --auto-sync --apply-tidy
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --minio-endpoint)
      MINIO_ENDPOINT="$2"; shift 2 ;;
    --minio-access)
      MINIO_ACCESS_KEY="$2"; shift 2 ;;
    --minio-secret)
      MINIO_SECRET_KEY="$2"; shift 2 ;;
    --seaweed-endpoint)
      SEAWEED_ENDPOINT="$2"; shift 2 ;;
    --seaweed-access)
      SEAWEED_ACCESS_KEY="$2"; shift 2 ;;
    --seaweed-secret)
      SEAWEED_SECRET_KEY="$2"; shift 2 ;;
    --workdir)
      WORKDIR="$2"; shift 2 ;;
    --tidy-prefixes)
      TIDY_PREFIXES="$2"; shift 2 ;;
    --auto-sync)
      AUTO_SYNC="true"; shift ;;
    --apply-tidy)
      APPLY_TIDY="true"; shift ;;
    --keep-artifacts)
      KEEP_ARTIFACTS="true"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

mkdir -p "$WORKDIR"
TS="$(date +%Y%m%d-%H%M%S)"
MINIO_MANIFEST="${WORKDIR}/minio-manifest-${TS}.jsonl"
SEAWEED_MANIFEST="${WORKDIR}/seaweed-manifest-${TS}.jsonl"
COMPARE_REPORT="${WORKDIR}/seaweed-compare-${TS}.json"

echo "[1/4] Building source manifest from ${MINIO_ENDPOINT}"
python3 scripts/storage_manifest.py \
  --endpoint "$MINIO_ENDPOINT" \
  --access-key "$MINIO_ACCESS_KEY" \
  --secret-key "$MINIO_SECRET_KEY" \
  --out "$MINIO_MANIFEST"

echo "[2/4] Building destination manifest from ${SEAWEED_ENDPOINT}"
python3 scripts/storage_manifest.py \
  --endpoint "$SEAWEED_ENDPOINT" \
  --access-key "$SEAWEED_ACCESS_KEY" \
  --secret-key "$SEAWEED_SECRET_KEY" \
  --out "$SEAWEED_MANIFEST"

echo "[3/4] Comparing manifests"
COMPARE_CLEAN="false"
if python3 scripts/storage_compare.py \
  --src "$MINIO_MANIFEST" \
  --dst "$SEAWEED_MANIFEST" \
  --out "$COMPARE_REPORT"; then
  COMPARE_CLEAN="true"
fi

if [[ "$COMPARE_CLEAN" != "true" && "$AUTO_SYNC" == "true" ]]; then
  echo "Drift detected. Running auto-sync from MinIO -> SeaweedFS."
  bash scripts/storage_sync.sh \
    --src-endpoint "$MINIO_ENDPOINT" \
    --src-access "$MINIO_ACCESS_KEY" \
    --src-secret "$MINIO_SECRET_KEY" \
    --dst-endpoint "$SEAWEED_ENDPOINT" \
    --dst-access "$SEAWEED_ACCESS_KEY" \
    --dst-secret "$SEAWEED_SECRET_KEY"

  python3 scripts/storage_manifest.py \
    --endpoint "$SEAWEED_ENDPOINT" \
    --access-key "$SEAWEED_ACCESS_KEY" \
    --secret-key "$SEAWEED_SECRET_KEY" \
    --out "$SEAWEED_MANIFEST"

  python3 scripts/storage_compare.py \
    --src "$MINIO_MANIFEST" \
    --dst "$SEAWEED_MANIFEST" \
    --out "$COMPARE_REPORT"
  COMPARE_CLEAN="true"
fi

echo "[4/4] Running Seaweed tidy (${APPLY_TIDY})"
TIDY_ARGS=(
  --endpoint "$SEAWEED_ENDPOINT"
  --access-key "$SEAWEED_ACCESS_KEY"
  --secret-key "$SEAWEED_SECRET_KEY"
  --prefixes "$TIDY_PREFIXES"
)
if [[ "$APPLY_TIDY" == "true" ]]; then
  TIDY_ARGS+=(--apply)
fi
TIDY_OUTPUT="$(bash scripts/seaweed_tidy.sh "${TIDY_ARGS[@]}")"

echo "=== Reconciliation Report ==="
cat "$COMPARE_REPORT"
echo
echo "=== Tidy Report ==="
echo "$TIDY_OUTPUT"

if [[ "$KEEP_ARTIFACTS" != "true" ]]; then
  rm -f "$MINIO_MANIFEST" "$SEAWEED_MANIFEST" "$COMPARE_REPORT"
fi

if [[ "$COMPARE_CLEAN" != "true" ]]; then
  echo "ERROR: Drift detected and auto-sync disabled. See report above." >&2
  exit 1
fi

echo "Seaweed reconciliation + tidy completed."
