#!/usr/bin/env python3
"""Summarize saved Amber retrieval traces without contacting services."""

import argparse
import collections
import hashlib
import json
import math
import os
from pathlib import Path

CANDIDATE_STAGES = {
    "cache_selection": "chunks",
    "pre_rerank_candidates": "chunks",
    "post_rerank_candidates": "chunks",
    "final_selection": "chunks",
    "generation_context": "candidates",
}
TIMING_FIELDS = (
    "total_ms",
    "analysis_ms",
    "retrieval_ms",
    "reranking_ms",
    "generation_ms",
)
RERANK_TIMING_FIELDS = (
    "ranker_load_ms",
    "executor_queue_ms",
    "ranker_execution_ms",
    "postprocess_ms",
)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _query_hash(query: object) -> str | None:
    if not isinstance(query, str):
        return None
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _candidate_stats(rows: list, active_doc_ids: set, active_chunk_ids: set) -> dict:
    chunk_ids = [
        row.get("chunk_id") or row.get("id")
        for row in rows
        if isinstance(row, dict) and (row.get("chunk_id") or row.get("id"))
    ]
    doc_ids = [
        row.get("document_id")
        for row in rows
        if isinstance(row, dict) and row.get("document_id")
    ]
    doc_counts = collections.Counter(doc_ids)
    unique_chunks = set(chunk_ids)
    unique_docs = set(doc_counts)
    row_count = len(rows)
    max_doc_rows = max(doc_counts.values(), default=0)
    return {
        "candidate_rows": row_count,
        "unique_chunks": len(unique_chunks),
        "duplicate_chunk_ids": len(chunk_ids) - len(unique_chunks),
        "unique_documents": len(unique_docs),
        "document_counts": dict(sorted(doc_counts.items())),
        "max_document_rows": max_doc_rows,
        "max_document_share": round(max_doc_rows / row_count, 4) if row_count else 0.0,
        "chunks_in_snapshot": len(unique_chunks & active_chunk_ids),
        "documents_in_snapshot": len(unique_docs & active_doc_ids),
    }


def _stage_events(events: list, stage: str, active_doc_ids: set, active_chunk_ids: set) -> list:
    output = []
    key = CANDIDATE_STAGES[stage]
    for event in events:
        if event.get("step") != stage:
            continue
        details = event.get("details")
        if not isinstance(details, dict) or not isinstance(details.get(key), list):
            raise ValueError(f"{stage}: expected details.{key} array")
        item = {
            "query_sha256": _query_hash(details.get("query")),
            "query_length": len(details["query"]) if isinstance(details.get("query"), str) else None,
            **_candidate_stats(details[key], active_doc_ids, active_chunk_ids),
        }
        if stage == "cache_selection":
            hit = details.get("cache_hit")
            item["cache_status"] = "hit" if hit is True else "miss" if hit is False else "unreported"
        if stage == "generation_context":
            item["reported_candidate_count"] = details.get("candidate_count")
            item["context_tokens_estimate"] = details.get("tokens")
            coverage = details.get("coverage")
            allowed = {
                "chunk_id",
                "document_id",
                "source_id",
                "original_chars",
                "post_pii_chars",
                "presented_chars",
                "truncated",
                "omitted",
                "synthetic",
                "reason",
            }
            item["coverage"] = (
                [
                    {
                        name: value
                        for name, value in row.items()
                        if name in allowed and isinstance(value, (str, int, bool, type(None)))
                    }
                    for row in coverage
                    if isinstance(row, dict)
                ]
                if isinstance(coverage, list)
                else None
            )
        output.append(item)
    return output


def _pre_post_overlap(events: list) -> list:
    pre_by_query = collections.defaultdict(list)
    post_by_query = collections.defaultdict(list)
    for event in events:
        stage = event.get("step")
        if stage not in {"pre_rerank_candidates", "post_rerank_candidates"}:
            continue
        details = event.get("details") or {}
        query_hash = _query_hash(details.get("query"))
        if query_hash:
            ids = {
                row.get("chunk_id") or row.get("id")
                for row in details.get("chunks", [])
                if isinstance(row, dict) and (row.get("chunk_id") or row.get("id"))
            }
            target = pre_by_query if stage == "pre_rerank_candidates" else post_by_query
            target[query_hash].append(ids)

    output = []
    for query_hash in sorted(pre_by_query.keys() & post_by_query.keys()):
        pre_group = pre_by_query[query_hash]
        post_group = post_by_query[query_hash]
        if len(pre_group) != 1 or len(post_group) != 1:
            output.append({"query_sha256": query_hash, "status": "repeated_query_events"})
            continue
        pre_rows = pre_group[0]
        post_rows = post_group[0]
        output.append({
            "query_sha256": query_hash,
            "status": "exact_query_match",
            "pre_candidate_count": len(pre_rows),
            "post_candidate_count": len(post_rows),
            "post_ids_also_in_pre": len(post_rows & pre_rows),
            "post_ids_outside_pre": len(post_rows - pre_rows),
        })
    return output


def _rerank_timing_events(events: list) -> list[dict]:
    output = []

    def add(step: str, stage: object, duration: object, details: dict) -> None:
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or duration < 0
        ):
            return
        item = {"step": step, "duration_ms": float(duration)}
        if stage in {"initial", "gap", "query_variant_common", "gap_common"}:
            item["stage"] = stage
        provider_timings = {}
        for key in RERANK_TIMING_FIELDS:
            value = details.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            ):
                continue
            provider_timings[key] = float(value)
        if provider_timings:
            item["provider_timings_ms"] = provider_timings
        output.append(item)

    for event in events:
        step = event.get("step")
        details = event.get("details")
        if not isinstance(details, dict):
            details = event
        if step in {"rerank", "common_query_rerank"}:
            duration = event.get("duration_ms", details.get("duration_ms"))
            attempted = details.get("rerank_attempted")
            # Older common-query traces predate the explicit call marker.
            if attempted is None:
                attempted = isinstance(duration, (int, float)) and duration > 0
            if attempted is True:
                add(step, details.get("stage"), duration, details)
        elif step == "sufficiency_check":
            gap_common = details.get("gap_common_rerank")
            if isinstance(gap_common, dict) and gap_common.get("rerank_attempted") is True:
                add(
                    "gap_common_rerank",
                    "gap_common",
                    gap_common.get("duration_ms"),
                    gap_common,
                )
    return output


def _summarize_trace(path: Path, data: dict, active_doc_ids: set, active_chunk_ids: set) -> dict:
    events = data.get("trace")
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        raise ValueError(f"{path}: expected trace array of objects")
    query = data.get("query")
    query_hash = _query_hash(query)
    stages = {
        stage: _stage_events(events, stage, active_doc_ids, active_chunk_ids)
        for stage in CANDIDATE_STAGES
    }

    cache_events = stages["cache_selection"]
    cache_counts = collections.Counter(event["cache_status"] for event in cache_events)
    vector_events = []
    for event in events:
        if event.get("step") == "vector_search":
            details = event.get("details") or {}
            if not isinstance(details, dict):
                raise ValueError(f"{path}: vector_search details must be an object")
            vector_events.append({
                "query_sha256": _query_hash(details.get("query")),
                "query_length": len(details["query"]) if isinstance(details.get("query"), str) else None,
                "results_count_observed": details.get("results_count"),
                "duration_ms_observed": event.get("duration_ms"),
            })

    sufficiency = []
    for event in events:
        if event.get("step") != "sufficiency_check":
            continue
        details = event.get("details") or {}
        if not isinstance(details, dict):
            raise ValueError(f"{path}: sufficiency_check details must be an object")
        gaps = details.get("gap_queries")
        fresh_gaps = details.get("fresh_gap_queries")
        gap_hits = details.get("gap_hits_added")
        sufficiency.append({
            "round": details.get("round"),
            "gap_query_count": len(gaps) if isinstance(gaps, list) else None,
            "fresh_gap_query_count": len(fresh_gaps) if isinstance(fresh_gaps, list) else None,
            "gap_hits_added_count": len(gap_hits) if isinstance(gap_hits, list) else None,
            "sufficient": details.get("sufficient"),
        })

    response = data.get("response") or {}
    if not isinstance(response, dict):
        raise ValueError(f"{path}: response must be an object")
    timing = response.get("timing") or {}
    if not isinstance(timing, dict):
        raise ValueError(f"{path}: response.timing must be an object")
    recorded_timing = {name: timing.get(name) for name in TIMING_FIELDS if name in timing}
    rerank_events = _rerank_timing_events(events)
    timed_events = [
        {"step": event.get("step"), "duration_ms": event.get("duration_ms")}
        for event in events
        if event.get("step") in {"vector_search", "sufficiency_check"}
        and isinstance(event.get("duration_ms"), (int, float))
        and not isinstance(event.get("duration_ms"), bool)
        and math.isfinite(float(event.get("duration_ms")))
        and event.get("duration_ms") > 0
    ]
    timed_events.extend(item.copy() for item in rerank_events if item["duration_ms"] > 0)

    overlaps = _pre_post_overlap(events)

    return {
        "file": str(path),
        "query_sha256": query_hash,
        "query_length": len(query) if isinstance(query, str) else None,
        "trace_event_count": len(events),
        "cache": {
            "selection_events": len(cache_events),
            "hits_observed": cache_counts["hit"],
            "misses_observed": cache_counts["miss"],
            "status_unreported": cache_counts["unreported"],
        },
        "vector_search_events": vector_events,
        "sufficiency_checks": sufficiency,
        "candidate_stages": stages,
        "pre_post_overlap_by_exact_query": overlaps,
        "rerank_events": rerank_events,
        "latency_observed": {
            "roundtrip_ms": response.get("roundtrip_ms"),
            "timing_ms": recorded_timing,
            "rerank_call_count": len(rerank_events),
            "reranking_duration_ms_observed": round(
                sum(item["duration_ms"] for item in rerank_events), 3
            ),
            "timed_events_ms": timed_events,
        },
    }


def build_report(corpus_path: Path, trace_paths: list[Path]) -> dict:
    corpus = _read_json(corpus_path)
    active_chunks = corpus.get("active_chunks")
    if not isinstance(active_chunks, list):
        raise ValueError(f"{corpus_path}: expected active_chunks array")
    active_doc_ids = {
        chunk.get("document_id")
        for chunk in active_chunks
        if isinstance(chunk, dict) and chunk.get("document_id")
    }
    active_chunk_ids = {
        chunk.get("id")
        for chunk in active_chunks
        if isinstance(chunk, dict) and chunk.get("id")
    }
    chunks_per_doc = collections.Counter(
        chunk.get("document_id")
        for chunk in active_chunks
        if isinstance(chunk, dict) and chunk.get("document_id")
    )
    inputs = [corpus_path, *trace_paths]
    return {
        "inputs": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in inputs
        ],
        "corpus_snapshot": {
            "active_chunk_count": len(active_chunks),
            "active_document_count": len(active_doc_ids),
            "chunks_per_document": dict(sorted(chunks_per_doc.items())),
            "scope_note": "Counts describe this supplied snapshot only, not the full tenant corpus.",
        },
        "recall_at_k": None,
        "recall_limit": "No reviewed query-specific relevant document/chunk labels were supplied.",
        "traces": [
            _summarize_trace(path, _read_json(path), active_doc_ids, active_chunk_ids)
            for path in trace_paths
        ],
        "limits": [
            "Citations are not treated as relevance labels.",
            "Candidate snapshots with duration_ms 0.0 are not latency measurements.",
            "final_selection events can belong to gap queries; generation_context is the actual context snapshot.",
            "Latency values are single recorded observations, not statistical comparisons.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--trace", required=True, action="append", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.corpus, args.trace)
        payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
