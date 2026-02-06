#!/usr/bin/env python3
"""Create deterministic JSONL manifest for an S3-compatible endpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from minio import Minio


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _sha256_for_object(client: Minio, bucket: str, key: str) -> str:
    digest = hashlib.sha256()
    response = client.get_object(bucket, key)
    try:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        response.close()
        response.release_conn()
    return digest.hexdigest()


def build_manifest(
    client: Minio,
    *,
    strict_hash: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    buckets = sorted(client.list_buckets(), key=lambda b: b.name)

    for bucket in buckets:
        objects = sorted(
            client.list_objects(bucket.name, recursive=True),
            key=lambda obj: obj.object_name,
        )
        for obj in objects:
            record: dict[str, Any] = {
                "bucket": bucket.name,
                "key": obj.object_name,
                "size": obj.size,
                "etag": obj.etag.strip('"') if obj.etag else None,
                "last_modified": _iso_or_none(obj.last_modified),
            }
            if strict_hash:
                record["sha256"] = _sha256_for_object(client, bucket.name, obj.object_name)
            records.append(record)
    return records


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate storage manifest JSONL.")
    parser.add_argument("--endpoint", required=True, help="S3 endpoint, e.g. localhost:9000")
    parser.add_argument("--access-key", required=True, help="S3 access key")
    parser.add_argument("--secret-key", required=True, help="S3 secret key")
    parser.add_argument("--secure", action="store_true", help="Use HTTPS")
    parser.add_argument("--strict-hash", action="store_true", help="Compute SHA256 per object")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    client = Minio(
        args.endpoint,
        access_key=args.access_key,
        secret_key=args.secret_key,
        secure=args.secure,
    )

    records = build_manifest(client, strict_hash=args.strict_hash)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    print(f"Wrote {len(records)} objects to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
