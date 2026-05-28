"""
LLM-as-Judge Evaluation
=======================

Loads a JSONL dataset (one record per line: {question, expected_answer,
contexts?, ground_truth?}), runs each question through the retrieval+generation
pipeline, then asks a judge LLM to score the answer along a small rubric.

Records and the aggregated metrics are persisted in BenchmarkRun (framework=judge).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.benchmark_run import BenchmarkRun, BenchmarkStatus

logger = logging.getLogger(__name__)


RUBRIC = [
    ("relevance", "Does the answer address the question directly?"),
    ("faithfulness", "Is the answer grounded in retrieved context (no hallucination)?"),
    ("completeness", "Does the answer cover the key points of the expected answer?"),
]

JUDGE_SYSTEM_PROMPT = """You are a strict but fair evaluator of RAG system answers.
Score each criterion from 0 to 10 (integers). Return ONLY valid JSON with this shape:
{"scores": {"relevance": int, "faithfulness": int, "completeness": int}, "rationale": "short text"}"""


@dataclass
class JudgeSample:
    question: str
    expected_answer: str
    ground_truth_context: str | None = None


@dataclass
class JudgeResult:
    question: str
    actual_answer: str
    scores: dict[str, int]
    rationale: str
    error: str | None = None


def load_dataset(path: Path) -> list[JudgeSample]:
    samples: list[JudgeSample] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no}: {exc}") from exc
            samples.append(
                JudgeSample(
                    question=row["question"],
                    expected_answer=row.get("expected_answer", row.get("ground_truth", "")),
                    ground_truth_context=row.get("contexts") or row.get("ground_truth_context"),
                )
            )
    return samples


def _parse_judge_response(text: str) -> tuple[dict[str, int], str]:
    """Extract scores+rationale from judge LLM raw output. Tolerant to noise."""
    # Strip code fences if any
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.DOTALL)
    # Find first JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("Judge output had no JSON object")
    data = json.loads(match.group(0))
    scores_raw = data.get("scores") or {}
    scores: dict[str, int] = {}
    for key, _desc in RUBRIC:
        try:
            scores[key] = int(scores_raw.get(key, 0))
        except (TypeError, ValueError):
            scores[key] = 0
    rationale = str(data.get("rationale", ""))
    return scores, rationale


async def run_judge_evaluation(
    session: AsyncSession,
    *,
    dataset_path: Path,
    tenant_id: str,
    judge_provider_name: str,
    judge_model: str,
    answerer: Callable[[str], "asyncio.Future[str] | str"],  # type: ignore[name-defined]  # noqa: F821
    judge_caller: Callable[[str, str], "asyncio.Future[str] | str"],  # type: ignore[name-defined]  # noqa: F821
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """
    Run the judge evaluation end-to-end. Persists a BenchmarkRun row.

    Args:
        answerer: async callable (question) -> answer (must run the RAG pipeline)
        judge_caller: async callable (system_prompt, user_prompt) -> raw judge text

    Returns:
        BenchmarkRun.id
    """
    import asyncio

    samples = load_dataset(dataset_path)
    total = len(samples)
    logger.info(f"Loaded {total} samples from {dataset_path}")

    run = BenchmarkRun(
        id=str(uuid4()),
        tenant_id=tenant_id,
        framework="judge",
        dataset_name=dataset_path.name,
        status=BenchmarkStatus.RUNNING,
        started_at=datetime.now(UTC),
        config={
            "judge_provider": judge_provider_name,
            "judge_model": judge_model,
            "rubric": [{"name": k, "description": d} for k, d in RUBRIC],
        },
    )
    session.add(run)
    await session.commit()

    results: list[JudgeResult] = []
    aggregates: dict[str, list[int]] = {k: [] for k, _ in RUBRIC}

    for idx, sample in enumerate(samples, start=1):
        try:
            answer_value = answerer(sample.question)
            actual = await answer_value if asyncio.iscoroutine(answer_value) else answer_value

            user_prompt = (
                f"Question:\n{sample.question}\n\n"
                f"Expected answer:\n{sample.expected_answer}\n\n"
                f"Actual answer:\n{actual}\n"
            )
            if sample.ground_truth_context:
                user_prompt += f"\nReference context:\n{sample.ground_truth_context}\n"

            judge_value = judge_caller(JUDGE_SYSTEM_PROMPT, user_prompt)
            judge_text = await judge_value if asyncio.iscoroutine(judge_value) else judge_value

            scores, rationale = _parse_judge_response(judge_text)
            for key, value in scores.items():
                aggregates.setdefault(key, []).append(value)

            results.append(
                JudgeResult(
                    question=sample.question,
                    actual_answer=str(actual),
                    scores=scores,
                    rationale=rationale,
                )
            )
        except Exception as exc:  # one bad sample shouldn't kill the run
            logger.warning(f"Sample #{idx} failed: {exc}")
            results.append(
                JudgeResult(
                    question=sample.question,
                    actual_answer="",
                    scores={k: 0 for k, _ in RUBRIC},
                    rationale="",
                    error=str(exc),
                )
            )

        if progress_callback:
            progress_callback(idx, total)

    metrics = {
        key: (sum(values) / len(values) if values else 0.0)
        for key, values in aggregates.items()
    }
    metrics["overall"] = (
        sum(metrics[k] for k, _ in RUBRIC) / max(len(RUBRIC), 1)
    )

    # Reload via fresh query to ensure we hold an attached instance
    res = await session.execute(select(BenchmarkRun).where(BenchmarkRun.id == run.id))
    persisted = res.scalar_one()
    persisted.metrics = metrics
    persisted.details = [
        {
            "question": r.question,
            "actual_answer": r.actual_answer,
            "scores": r.scores,
            "rationale": r.rationale,
            "error": r.error,
        }
        for r in results
    ]
    persisted.status = BenchmarkStatus.COMPLETED
    persisted.completed_at = datetime.now(UTC)
    await session.commit()

    logger.info(f"Judge eval {run.id} complete: {metrics}")
    return run.id
