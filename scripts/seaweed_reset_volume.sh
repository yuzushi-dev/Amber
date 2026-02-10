#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
SEAWEED_MASTER_VOLUME="${SEAWEED_MASTER_VOLUME:-amber_20_graphrag-seaweed-master}"
SEAWEED_VOLUME_VOLUME="${SEAWEED_VOLUME_VOLUME:-amber_20_graphrag-seaweed-volume}"
SEAWEED_FILER_VOLUME="${SEAWEED_FILER_VOLUME:-amber_20_graphrag-seaweed-filer}"
FORCE="false"

usage() {
  cat <<'EOF'
Reset local SeaweedFS data volumes safely (development usage).

Usage:
  bash scripts/seaweed_reset_volume.sh [--force]

What it does:
  1) Stops Seaweed services (master/volume/filer/s3)
  2) Clears all Seaweed Docker volume contents
  3) Starts Seaweed services again
  4) Prints resulting volume usage

Notes:
  - This deletes all data currently stored in SeaweedFS.
  - Use only when MinIO (or another source of truth) still has your data.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$FORCE" != "true" ]]; then
  echo "WARNING: This will permanently delete all SeaweedFS data in volumes:"
  echo "  - $SEAWEED_MASTER_VOLUME"
  echo "  - $SEAWEED_VOLUME_VOLUME"
  echo "  - $SEAWEED_FILER_VOLUME"
  read -r -p "Type RESET to continue: " confirm
  if [[ "$confirm" != "RESET" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

echo "[1/4] Stopping SeaweedFS services..."
docker compose -f "$COMPOSE_FILE" stop seaweed-s3 seaweed-filer seaweed-volume seaweed-master

echo "[2/4] Clearing SeaweedFS volumes..."
for vol in "$SEAWEED_MASTER_VOLUME" "$SEAWEED_VOLUME_VOLUME" "$SEAWEED_FILER_VOLUME"; do
  echo "  Clearing $vol..."
  docker run --rm -v "$vol":/data alpine sh -lc 'rm -rf /data/* /data/.[!.]* /data/..?*; mkdir -p /data'
done

echo "[3/4] Starting SeaweedFS services..."
docker compose -f "$COMPOSE_FILE" up -d seaweed-master seaweed-volume seaweed-filer seaweed-s3

echo "[4/4] Post-reset volume usage:"
for vol in "$SEAWEED_MASTER_VOLUME" "$SEAWEED_VOLUME_VOLUME" "$SEAWEED_FILER_VOLUME"; do
  echo "  $vol:"
  docker run --rm -v "$vol":/data alpine sh -lc 'du -sh /data; df -h /data'
done

echo "SeaweedFS volume reset completed."
