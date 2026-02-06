#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/storage_sync.sh \
    --src-endpoint <host:port> --src-access <key> --src-secret <secret> \
    --dst-endpoint <host:port> --dst-access <key> --dst-secret <secret> \
    [--src-secure] [--dst-secure]

Notes:
  - Copies all buckets and objects from source to destination.
  - Existing destination objects are skipped when size+etag match.
  - This is safe to re-run for incremental sync.
EOF
}

SRC_ENDPOINT=""
SRC_ACCESS=""
SRC_SECRET=""
DST_ENDPOINT=""
DST_ACCESS=""
DST_SECRET=""
SRC_SECURE="false"
DST_SECURE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src-endpoint)
      SRC_ENDPOINT="$2"
      shift 2
      ;;
    --src-access)
      SRC_ACCESS="$2"
      shift 2
      ;;
    --src-secret)
      SRC_SECRET="$2"
      shift 2
      ;;
    --dst-endpoint)
      DST_ENDPOINT="$2"
      shift 2
      ;;
    --dst-access)
      DST_ACCESS="$2"
      shift 2
      ;;
    --dst-secret)
      DST_SECRET="$2"
      shift 2
      ;;
    --src-secure)
      SRC_SECURE="true"
      shift
      ;;
    --dst-secure)
      DST_SECURE="true"
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

if [[ -z "$SRC_ENDPOINT" || -z "$SRC_ACCESS" || -z "$SRC_SECRET" || -z "$DST_ENDPOINT" || -z "$DST_ACCESS" || -z "$DST_SECRET" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 2
fi

python3 - "$SRC_ENDPOINT" "$SRC_ACCESS" "$SRC_SECRET" "$SRC_SECURE" "$DST_ENDPOINT" "$DST_ACCESS" "$DST_SECRET" "$DST_SECURE" <<'PY'
from __future__ import annotations

import json
import sys
from typing import Any

from minio import Minio
from minio.error import S3Error


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def etag(value: str | None) -> str:
    return (value or "").strip('"')


def main(argv: list[str]) -> int:
    if len(argv) != 8:
        raise SystemExit("expected 8 args")

    src_endpoint, src_access, src_secret, src_secure, dst_endpoint, dst_access, dst_secret, dst_secure = argv

    src = Minio(
        src_endpoint,
        access_key=src_access,
        secret_key=src_secret,
        secure=as_bool(src_secure),
    )
    dst = Minio(
        dst_endpoint,
        access_key=dst_access,
        secret_key=dst_secret,
        secure=as_bool(dst_secure),
    )

    summary: dict[str, Any] = {
        "buckets": 0,
        "objects_seen": 0,
        "objects_copied": 0,
        "objects_skipped": 0,
        "copy_errors": 0,
    }

    buckets = sorted(src.list_buckets(), key=lambda b: b.name)
    summary["buckets"] = len(buckets)

    for bucket in buckets:
        if not dst.bucket_exists(bucket.name):
            dst.make_bucket(bucket.name)

        for obj in src.list_objects(bucket.name, recursive=True):
            summary["objects_seen"] += 1
            should_copy = True

            try:
                dst_stat = dst.stat_object(bucket.name, obj.object_name)
                if dst_stat.size == obj.size and etag(dst_stat.etag) == etag(obj.etag):
                    should_copy = False
            except S3Error:
                should_copy = True

            if not should_copy:
                summary["objects_skipped"] += 1
                continue

            response = src.get_object(bucket.name, obj.object_name)
            try:
                dst.put_object(
                    bucket.name,
                    obj.object_name,
                    data=response,
                    length=obj.size,
                    content_type="application/octet-stream",
                )
                summary["objects_copied"] += 1
            except Exception:
                summary["copy_errors"] += 1
                raise
            finally:
                response.close()
                response.release_conn()

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
PY
