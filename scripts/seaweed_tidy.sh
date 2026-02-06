#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${SEAWEED_ENDPOINT:-localhost:8333}"
ACCESS_KEY="${OBJECT_STORAGE_ACCESS_KEY:-minioadmin}"
SECRET_KEY="${OBJECT_STORAGE_SECRET_KEY:-minioadmin}"
SECURE="false"
APPLY="false"
PREFIXES="probe-,compat-,compat-debug-,migration-smoke"

usage() {
  cat <<'EOF'
Prune temporary/test buckets from SeaweedFS S3.

Usage:
  bash scripts/seaweed_tidy.sh [options]

Options:
  --endpoint <host:port>    S3 endpoint (default: localhost:8333)
  --access-key <key>        Access key (default: OBJECT_STORAGE_ACCESS_KEY or minioadmin)
  --secret-key <key>        Secret key (default: OBJECT_STORAGE_SECRET_KEY or minioadmin)
  --secure                  Use HTTPS
  --prefixes <csv>          Bucket name prefixes to prune
  --apply                   Apply deletions (default is dry-run)

Examples:
  bash scripts/seaweed_tidy.sh
  bash scripts/seaweed_tidy.sh --apply
  bash scripts/seaweed_tidy.sh --prefixes "tmp-,probe-,compat-" --apply
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --endpoint)
      ENDPOINT="$2"; shift 2 ;;
    --access-key)
      ACCESS_KEY="$2"; shift 2 ;;
    --secret-key)
      SECRET_KEY="$2"; shift 2 ;;
    --secure)
      SECURE="true"; shift ;;
    --prefixes)
      PREFIXES="$2"; shift 2 ;;
    --apply)
      APPLY="true"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

python3 - "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY" "$SECURE" "$PREFIXES" "$APPLY" <<'PY'
from __future__ import annotations

import json
import sys
from typing import Any

from minio import Minio


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        raise SystemExit("expected 6 args")

    endpoint, access_key, secret_key, secure_flag, prefixes_csv, apply_flag = argv
    prefixes = tuple(p.strip() for p in prefixes_csv.split(",") if p.strip())
    apply = as_bool(apply_flag)

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=as_bool(secure_flag))

    matched: list[str] = []
    deleted_buckets = 0
    deleted_objects = 0

    for bucket in sorted(client.list_buckets(), key=lambda b: b.name):
        if not bucket.name.startswith(prefixes):
            continue
        matched.append(bucket.name)

        if not apply:
            continue

        for obj in client.list_objects(bucket.name, recursive=True):
            client.remove_object(bucket.name, obj.object_name)
            deleted_objects += 1
        client.remove_bucket(bucket.name)
        deleted_buckets += 1

    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "endpoint": endpoint,
        "prefixes": list(prefixes),
        "matched_buckets": matched,
        "deleted_buckets": deleted_buckets,
        "deleted_objects": deleted_objects,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
PY
