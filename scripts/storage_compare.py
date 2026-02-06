#!/usr/bin/env python3
"""Compare two object-storage manifests and report drift."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _record_key(record: dict[str, Any]) -> tuple[str, str]:
    return str(record["bucket"]), str(record["key"])


def _record_id_text(key: tuple[str, str]) -> str:
    return f"{key[0]}/{key[1]}"


def _records_mismatch(src: dict[str, Any], dst: dict[str, Any]) -> bool:
    # Size and ETag should always match for deterministic copy verification.
    if src.get("size") != dst.get("size"):
        return True
    if src.get("etag") != dst.get("etag"):
        return True

    # Optional strict-hash field: compare only if both manifests contain it.
    src_hash = src.get("sha256")
    dst_hash = dst.get("sha256")
    if src_hash is not None and dst_hash is not None and src_hash != dst_hash:
        return True
    return False


def compare_records(src_records: list[dict[str, Any]], dst_records: list[dict[str, Any]]) -> dict[str, Any]:
    src_index = {_record_key(record): record for record in src_records}
    dst_index = {_record_key(record): record for record in dst_records}

    src_keys = set(src_index.keys())
    dst_keys = set(dst_index.keys())

    missing = sorted(src_keys - dst_keys)
    extra = sorted(dst_keys - src_keys)

    mismatched: list[str] = []
    for key in sorted(src_keys & dst_keys):
        if _records_mismatch(src_index[key], dst_index[key]):
            mismatched.append(_record_id_text(key))

    return {
        "source_count": len(src_records),
        "destination_count": len(dst_records),
        "missing_in_dst": len(missing),
        "extra_in_dst": len(extra),
        "mismatched": len(mismatched),
        "missing_keys": [_record_id_text(key) for key in missing],
        "extra_keys": [_record_id_text(key) for key in extra],
        "mismatched_keys": mismatched,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_no}: {exc}") from exc
            if "bucket" not in record or "key" not in record:
                raise ValueError(f"Missing bucket/key in {path}:{line_no}")
            records.append(record)
    return records


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare storage manifest JSONL files.")
    parser.add_argument("--src", required=True, help="Source manifest JSONL path")
    parser.add_argument("--dst", required=True, help="Destination manifest JSONL path")
    parser.add_argument(
        "--out",
        help="Optional path for report JSON output. If omitted, prints to stdout only.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    src_path = Path(args.src)
    dst_path = Path(args.dst)

    src_records = _load_jsonl(src_path)
    dst_records = _load_jsonl(dst_path)

    report = compare_records(src_records, dst_records)
    report_text = json.dumps(report, indent=2, sort_keys=True)

    print(report_text)
    if args.out:
        Path(args.out).write_text(report_text + "\n", encoding="utf-8")

    if report["missing_in_dst"] or report["extra_in_dst"] or report["mismatched"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
