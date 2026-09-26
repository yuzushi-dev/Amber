import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_keeps_trace_summary_private_and_uses_generation_context(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "summarize_retrieval_traces.py"
    corpus = tmp_path / "corpus.json"
    trace = tmp_path / "trace.json"
    output = tmp_path / "report.json"
    raw_query = "outer raw query must not leak"
    raw_answer = "answer body must not leak"
    gap_query = "private gap query must not leak"
    corpus.write_text(json.dumps({"active_chunks": [
        {"id": "c1", "document_id": "d1"},
        {"id": "c2", "document_id": "d2"},
    ]}), encoding="utf-8")
    trace.write_text(json.dumps({
        "query": raw_query,
        "trace": [
            {"step": "cache_selection", "details": {"query": raw_query, "cache_hit": True, "chunks": [{"chunk_id": "c1", "document_id": "d1"}]}},
            {"step": "cache_selection", "details": {"query": "unreported", "chunks": []}},
            {"step": "cache_selection", "details": {"query": "miss", "cache_hit": False, "chunks": []}},
            {"step": "pre_rerank_candidates", "details": {"query": "same search", "chunks": [{"chunk_id": "c1", "document_id": "d1"}, {"chunk_id": "c2", "document_id": "d2"}]}},
            {"step": "post_rerank_candidates", "details": {"query": "same search", "chunks": [{"chunk_id": "c2", "document_id": "d2"}]}},
            {"step": "rerank", "duration_ms": 10.0, "details": {
                "stage": "gap",
                "ranker_load_ms": 0.2,
                "executor_queue_ms": 0.3,
                "ranker_execution_ms": 9.1,
                "postprocess_ms": 0.4,
            }},
            {"step": "common_query_rerank", "duration_ms": 4.5, "details": {
                "stage": "query_variant_common",
                "rerank_attempted": True,
                "executor_queue_ms": 0.7,
                "ranker_execution_ms": 3.8,
                "postprocess_ms": "invalid",
            }},
            {"step": "sufficiency_check", "details": {
                "round": 1,
                "gap_queries": [gap_query],
                "fresh_gap_queries": [gap_query],
                "sufficient": False,
                "gap_common_rerank": {
                    "rerank_attempted": True,
                    "duration_ms": 8.25,
                    "ranker_execution_ms": 7.5,
                },
            }},
            {"step": "sufficiency_check", "details": {
                "round": 2,
                "gap_queries": [],
                "fresh_gap_queries": [],
                "sufficient": True,
                "gap_common_rerank": {
                    "rerank_attempted": True,
                    "duration_ms": 6.0,
                },
            }},
            {"step": "final_selection", "details": {"chunks": [{"chunk_id": "c1", "document_id": "d1"}]}},
            {"step": "final_selection", "details": {"chunks": [{"chunk_id": "wrong-last", "document_id": "wrong"}]}},
            {"step": "generation_context", "details": {
                "candidate_count": 1,
                "tokens": 17,
                "candidates": [{"chunk_id": "c2", "document_id": "d2"}],
                "coverage": [{
                    "chunk_id": "c2",
                    "document_id": "d2",
                    "source_id": 4,
                    "original_chars": 30,
                    "post_pii_chars": 28,
                    "presented_chars": 20,
                    "truncated": True,
                    "omitted": False,
                    "synthetic": False,
                    "reason": "included",
                    "content": "COVERAGE_CONTENT_CANARY",
                }],
            }},
            {"step": "vector_search", "duration_ms": 12.5, "details": {"query": gap_query, "results_count": 4}},
        ],
        "response": {"answer": raw_answer, "roundtrip_ms": 20, "timing": {"total_ms": 20, "retrieval_ms": 12}},
    }), encoding="utf-8")

    command = [sys.executable, str(script), "--corpus", str(corpus), "--trace", str(trace), "--out", str(output)]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    payload = output.read_text(encoding="utf-8")
    report = json.loads(payload)
    sample = report["traces"][0]
    assert sample["cache"] == {"selection_events": 3, "hits_observed": 1, "misses_observed": 1, "status_unreported": 1}
    context = sample["candidate_stages"]["generation_context"][0]
    assert context["unique_chunks"] == 1 and context["context_tokens_estimate"] == 17
    assert context["coverage"] == [{
        "chunk_id": "c2",
        "document_id": "d2",
        "source_id": 4,
        "original_chars": 30,
        "post_pii_chars": 28,
        "presented_chars": 20,
        "truncated": True,
        "omitted": False,
        "synthetic": False,
        "reason": "included",
    }]
    assert "COVERAGE_CONTENT_CANARY" not in payload
    assert sample["candidate_stages"]["final_selection"][-1]["document_counts"] == {"wrong": 1}
    assert "generation_context_delta_vs_initial_cache" not in sample
    assert sample["pre_post_overlap_by_exact_query"][0]["post_ids_also_in_pre"] == 1
    assert sample["latency_observed"]["rerank_call_count"] == 4
    assert sample["latency_observed"]["reranking_duration_ms_observed"] == 28.75
    assert sample["rerank_events"] == [
        {
            "step": "rerank",
            "stage": "gap",
            "duration_ms": 10.0,
            "provider_timings_ms": {
                "ranker_load_ms": 0.2,
                "executor_queue_ms": 0.3,
                "ranker_execution_ms": 9.1,
                "postprocess_ms": 0.4,
            },
        },
        {
            "step": "common_query_rerank",
            "stage": "query_variant_common",
            "duration_ms": 4.5,
            "provider_timings_ms": {
                "executor_queue_ms": 0.7,
                "ranker_execution_ms": 3.8,
            },
        },
        {
            "step": "gap_common_rerank",
            "stage": "gap_common",
            "duration_ms": 8.25,
            "provider_timings_ms": {"ranker_execution_ms": 7.5},
        },
        {
            "step": "gap_common_rerank",
            "stage": "gap_common",
            "duration_ms": 6.0,
        },
    ]
    assert raw_query not in payload and raw_answer not in payload and gap_query not in payload
    assert os.stat(output).st_mode & 0o777 == 0o600

    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode != 0
    assert output.read_text(encoding="utf-8") == payload

    trace_data = json.loads(trace.read_text(encoding="utf-8"))
    generation_event = next(event for event in trace_data["trace"] if event["step"] == "generation_context")
    del generation_event["details"]["coverage"]
    unavailable_trace = tmp_path / "trace-without-coverage.json"
    unavailable_trace.write_text(json.dumps(trace_data), encoding="utf-8")
    unavailable_output = tmp_path / "report-without-coverage.json"
    unavailable = subprocess.run(
        [sys.executable, str(script), "--corpus", str(corpus), "--trace", str(unavailable_trace), "--out", str(unavailable_output)],
        capture_output=True,
        text=True,
    )
    assert unavailable.returncode == 0, unavailable.stderr
    absent_context = json.loads(unavailable_output.read_text(encoding="utf-8"))["traces"][0]["candidate_stages"]["generation_context"][0]
    assert absent_context["coverage"] is None
