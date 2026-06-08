#!/bin/bash
# Daily cron: archive yesterday's amber API logs to /var/log/amber/YYYY-MM-DD.log.gz
# Install: cp scripts/amber_log_archive.sh /etc/cron.daily/amber-log-archive && chmod +x /etc/cron.daily/amber-log-archive

set -euo pipefail

CONTAINER="${AMBER_CONTAINER:-amber2-api-1}"
LOG_DIR="${AMBER_LOG_DIR:-/var/log/amber}"
DATE=$(date -d yesterday +%Y-%m-%d)
OUT="${LOG_DIR}/${DATE}.log.gz"

mkdir -p "$LOG_DIR"

if [ -f "$OUT" ]; then
    echo "Already archived: $OUT"
    exit 0
fi

SINCE="${DATE}T00:00:00Z"
UNTIL="${DATE}T23:59:59Z"

docker logs "$CONTAINER" --since "$SINCE" --until "$UNTIL" 2>&1 \
    | grep '"event":"request_processed"' \
    | gzip > "$OUT"

COUNT=$(zcat "$OUT" | wc -l)
echo "Archived ${DATE}: ${COUNT} request_processed events → ${OUT}"
