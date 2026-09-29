import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.admin_ops.application.evaluation import run_eval


def _dataset(tmp_path, *queries):
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            [{"query": q, "ideal_context": f"IDEAL CONTEXT {q}", "ideal_answer": "ideal"} for q in queries]
        )
    )
    return path


def _judge(faith=0.8, rel=0.6):
    judge = SimpleNamespace(
        evaluate_faithfulness=AsyncMock(return_value=SimpleNamespace(score=faith, reasoning="f")),
        evaluate_relevance=AsyncMock(return_value=SimpleNamespace(score=rel, reasoning="r")),
    )
    return judge


@pytest.mark.asyncio
async def test_judge_sees_real_answer_and_full_chunks_not_ideal_context(tmp_path):
    long_chunk = "x" * 500  # well past the 100-char API source preview
    answer_fn = AsyncMock(return_value=("real answer", [long_chunk, "second chunk"]))
    judge = _judge()

    results = await run_eval.run_evaluation(
        _dataset(tmp_path, "q1"), tenant_id="tenant-1", answer_fn=answer_fn, judge=judge
    )

    answer_fn.assert_awaited_once_with("q1", "tenant-1")
    kwargs = judge.evaluate_faithfulness.await_args.kwargs
    assert kwargs["answer"] == "real answer"
    assert kwargs["context"] == f"{long_chunk}\n\nsecond chunk"
    assert "IDEAL CONTEXT" not in kwargs["context"]
    judge.evaluate_relevance.assert_awaited_once_with(query="q1", answer="real answer")
    assert results == [
        {
            "query": "q1",
            "status": "scored",
            "answer": "real answer",
            "contexts_count": 2,
            "faithfulness": 0.8,
            "relevance": 0.6,
            "reasoning_faith": "f",
            "reasoning_rel": "r",
        }
    ]


@pytest.mark.asyncio
async def test_no_retrieval_and_errors_are_recorded_not_scored(tmp_path, capsys):
    outcomes = {
        "scored": ("answer", ["chunk"]),
        "empty": ("", []),
        "boom": RuntimeError("milvus down"),
    }

    async def answer_fn(query, _tenant):
        outcome = outcomes[query]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    judge = _judge(faith=1.0, rel=0.5)

    results = await run_eval.run_evaluation(
        _dataset(tmp_path, "empty", "boom", "scored"), answer_fn=answer_fn, judge=judge
    )

    assert [(r["query"], r["status"]) for r in results] == [
        ("empty", "no_retrieval"),
        ("boom", "error"),
        ("scored", "scored"),
    ]
    assert results[1]["error"] == "milvus down"
    # Only the scored item reaches the judge; the empty one must not be rated faithful.
    assert judge.evaluate_faithfulness.await_count == 1
    out = capsys.readouterr().out
    assert "Scored: 1  No retrieval: 1  Errors: 1" in out
    assert "Average Faithfulness: 1.00" in out


@pytest.mark.asyncio
async def test_judge_failure_is_an_error_not_a_crash(tmp_path):
    judge = _judge()
    judge.evaluate_faithfulness.side_effect = TimeoutError("judge timeout")

    results = await run_eval.run_evaluation(
        _dataset(tmp_path, "q1", "q2"),
        answer_fn=AsyncMock(return_value=("a", ["c"])),
        judge=judge,
    )

    assert [r["status"] for r in results] == ["error", "error"]


@pytest.mark.asyncio
async def test_all_items_failing_reports_na_instead_of_dividing_by_zero(tmp_path, capsys):
    results = await run_eval.run_evaluation(
        _dataset(tmp_path, "q1"),
        answer_fn=AsyncMock(return_value=("", [])),
        judge=_judge(),
    )

    assert results[0]["status"] == "no_retrieval"
    out = capsys.readouterr().out
    assert "Average Faithfulness: n/a" in out
    assert "Average Relevance: n/a" in out


@pytest.mark.asyncio
async def test_pipeline_answerer_uses_a_fresh_privileged_session_per_call(monkeypatch):
    """Each call opens its own session and re-applies the worker RLS GUCs."""
    from contextlib import asynccontextmanager

    from src.amber_platform import composition_root
    from src.cli import _session
    from src.core.database import session as db_session

    sessions, configured, retrieve_calls = [], [], []

    @asynccontextmanager
    async def fake_scope():
        s = object()
        sessions.append(s)
        yield s

    async def fake_configure(session, tenant_id):
        configured.append((session, tenant_id))

    chunks = [{"content": "full chunk text " * 20}]

    def fake_retrieval(session):
        async def retrieve(**kwargs):
            retrieve_calls.append(kwargs)
            return SimpleNamespace(chunks=chunks if kwargs["query"] == "hit" else [])

        return SimpleNamespace(retrieve=retrieve)

    def fake_generation(session):
        return SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(answer="gen answer")))

    monkeypatch.setattr(_session, "session_scope", fake_scope)
    monkeypatch.setattr(db_session, "configure_worker_session", fake_configure)
    monkeypatch.setattr(composition_root, "build_retrieval_service", fake_retrieval)
    monkeypatch.setattr(composition_root, "build_generation_service", fake_generation)

    from src.cli.commands.eval import answer_with_pipeline

    assert await answer_with_pipeline("hit", "tenant-1") == ("gen answer", [chunks[0]["content"]])
    assert await answer_with_pipeline("miss", "tenant-1") == ("", [])

    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    assert configured == [(sessions[0], "tenant-1"), (sessions[1], "tenant-1")]
    assert all(c["for_generation"] and c["tenant_id"] == "tenant-1" for c in retrieve_calls)
    assert retrieve_calls[0]["query_scopes"] is not None


def test_init_providers_from_settings_prefers_provider_block_keys():
    from src.core.generation.infrastructure.providers.factory import init_providers_from_settings

    settings = SimpleNamespace(
        providers=SimpleNamespace(openai_api_key="from-providers", anthropic_api_key=None),
        openai_api_key="from-root",
        anthropic_api_key="anthropic-root",
        ollama_base_url="http://ollama",
        default_llm_provider="openai",
        default_llm_model="m",
        default_embedding_provider="openai",
        default_embedding_model="e",
        llm_fallback_local=None,
        llm_fallback_economy=None,
        llm_fallback_standard=None,
        llm_fallback_premium=None,
        embedding_fallback_order=None,
        openrouter_api_key=None,
        openrouter_base_url=None,
        nvidia_nim_api_key=None,
        nvidia_nim_base_url=None,
        llm_fallback_enabled=True,
        ollama_cloud_base_url=None,
        ollama_cloud_api_keys=[],
    )
    captured = {}

    result = init_providers_from_settings(settings, lambda **kw: captured.update(kw) or "factory")

    assert result == "factory"
    assert captured["openai_api_key"] == "from-providers"
    assert captured["anthropic_api_key"] == "anthropic-root"
    assert captured["ollama_base_url"] == "http://ollama"
