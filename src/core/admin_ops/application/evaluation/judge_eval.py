"""
LLM-as-Judge Evaluation
=======================

Loads samples (JSONL or via Locomo adapter), runs each question through the
RAG pipeline, then asks a judge LLM to score the answer along a rubric.
Progress + status are published on Redis (``eval:state:{run_id}`` and
``eval:logs:{run_id}``) so TUI/UI can show them live.

Results land in ``BenchmarkRun`` (``framework`` discriminator).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.benchmark_run import BenchmarkRun, BenchmarkStatus

logger = logging.getLogger(__name__)


# Default rubric for ad-hoc JSONL datasets.
DEFAULT_RUBRIC: list[tuple[str, str]] = [
    ("relevance", "Does the answer address the question directly?"),
    ("faithfulness", "Is the answer grounded in retrieved context (no hallucination)?"),
    ("completeness", "Does the answer cover the key points of the expected answer?"),
]


JUDGE_SYSTEM_PROMPT_TPL = """You are a strict but fair evaluator of RAG system answers.
Score each criterion from 0 to 10 (integers). Return ONLY valid JSON with this shape:
{{"scores": {{{score_keys}}}, "rationale": "short text"}}"""


def build_judge_system_prompt(rubric: Sequence[tuple[str, str]]) -> str:
    score_keys = ", ".join(f'"{k}": int' for k, _ in rubric)
    return JUDGE_SYSTEM_PROMPT_TPL.format(score_keys=score_keys)


@dataclass
class JudgeSample:
    question: str
    expected_answer: str
    ground_truth_context: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgeResult:
    question: str
    actual_answer: str
    scores: dict[str, int]
    rationale: str
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def load_jsonl(path: Path) -> list[JudgeSample]:
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
                    extra={
                        k: v
                        for k, v in row.items()
                        if k not in ("question", "expected_answer", "ground_truth", "contexts",
                                     "ground_truth_context")
                    },
                )
            )
    return samples


# Backwards-compat alias (older imports referenced ``load_dataset``).
load_dataset = load_jsonl


def _parse_judge_response(
    text: str, rubric: Sequence[tuple[str, str]]
) -> tuple[dict[str, int], str]:
    """Extract scores+rationale from judge LLM raw output. Tolerant to noise."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.DOTALL)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("Judge output had no JSON object")
    data = json.loads(match.group(0))
    scores_raw = data.get("scores") or {}
    scores: dict[str, int] = {}
    for key, _desc in rubric:
        raw = scores_raw.get(key, 0)
        try:
            # Tolerate float-like judge output ("8.5", 8.5) by rounding instead of failing to 0.
            scores[key] = int(round(float(raw)))
        except (TypeError, ValueError):
            scores[key] = 0
    rationale = str(data.get("rationale", ""))
    return scores, rationale


# ---------------------------------------------------------------------------
# Redis pub/sub helpers (best-effort; no-op when Redis is unreachable)
# ---------------------------------------------------------------------------


def _publish_eval(run_id: str, payload: dict[str, Any], *, kind: str = "state") -> None:
    """Publish + cache eval status/logs on Redis. Best-effort, never raises."""
    try:
        import redis  # type: ignore

        from src.api.config import settings  # local import to avoid hard dep
    except Exception:  # pragma: no cover
        return

    try:
        client = redis.Redis.from_url(settings.db.redis_url)
        try:
            raw = json.dumps(payload, default=str)
            if kind == "state":
                client.setex(f"eval:state:{run_id}", 3600, raw)
                client.publish(f"eval:{run_id}:status", raw)
            elif kind == "log":
                client.publish(f"eval:{run_id}:logs", raw)
                client.lpush(f"eval:logs:{run_id}", raw)
                client.ltrim(f"eval:logs:{run_id}", 0, 500)
                client.expire(f"eval:logs:{run_id}", 3600)
        finally:
            client.close()
    except Exception as exc:  # pragma: no cover
        logger.debug(f"Eval Redis publish failed: {exc}")


def publish_eval_state(
    run_id: str,
    *,
    status: str,
    progress: int,
    done: int = 0,
    total: int = 0,
    error: str | None = None,
) -> None:
    payload = {
        "run_id": run_id,
        "status": status,
        "progress": progress,
        "done": done,
        "total": total,
    }
    if error:
        payload["error"] = error
    _publish_eval(run_id, payload, kind="state")


def publish_eval_log(run_id: str, message: str) -> None:
    _publish_eval(run_id, {"message": message, "ts": datetime.now(UTC).isoformat()}, kind="log")


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


AnswerFn = Callable[[JudgeSample], "Awaitable[str] | str"]
JudgeFn = Callable[[str, str], "Awaitable[str] | str"]


async def run_judge_evaluation(
    session: AsyncSession,
    *,
    samples: list[JudgeSample] | None = None,
    dataset_path: Path | None = None,
    tenant_id: str,
    judge_provider_name: str,
    judge_model: str,
    answerer: AnswerFn,
    judge_caller: JudgeFn,
    rubric: Sequence[tuple[str, str]] = DEFAULT_RUBRIC,
    framework: str = "judge",
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """
    Generic judge runner. Pass ``samples`` (already prepared) or ``dataset_path``
    for the default JSONL loader. Returns the persisted BenchmarkRun.id.
    """
    if samples is None:
        if dataset_path is None:
            raise ValueError("Either samples or dataset_path must be provided")
        samples = load_jsonl(dataset_path)

    total = len(samples)
    dataset_name = dataset_path.name if dataset_path else f"adhoc-{framework}"
    logger.info(f"Starting eval framework={framework} samples={total}")

    run = BenchmarkRun(
        id=str(uuid4()),
        tenant_id=tenant_id,
        framework=framework,
        dataset_name=dataset_name,
        status=BenchmarkStatus.RUNNING,
        started_at=datetime.now(UTC),
        config={
            "judge_provider": judge_provider_name,
            "judge_model": judge_model,
            "rubric": [{"name": k, "description": d} for k, d in rubric],
        },
    )
    session.add(run)
    await session.commit()

    publish_eval_state(run.id, status="running", progress=0, done=0, total=total)
    publish_eval_log(run.id, f"Started {framework} eval with {total} samples")

    judge_system_prompt = build_judge_system_prompt(rubric)
    results: list[JudgeResult] = []
    aggregates: dict[str, list[int]] = {k: [] for k, _ in rubric}

    for idx, sample in enumerate(samples, start=1):
        try:
            answer_value = answerer(sample)
            actual = await answer_value if asyncio.iscoroutine(answer_value) else answer_value

            user_prompt = (
                f"Question:\n{sample.question}\n\n"
                f"Expected answer:\n{sample.expected_answer}\n\n"
                f"Actual answer:\n{actual}\n"
            )
            if sample.ground_truth_context:
                user_prompt += f"\nReference context:\n{sample.ground_truth_context}\n"

            judge_value = judge_caller(judge_system_prompt, user_prompt)
            judge_text = await judge_value if asyncio.iscoroutine(judge_value) else judge_value

            scores, rationale = _parse_judge_response(judge_text, rubric)
            for key, value in scores.items():
                aggregates.setdefault(key, []).append(value)

            results.append(
                JudgeResult(
                    question=sample.question,
                    actual_answer=str(actual),
                    scores=scores,
                    rationale=rationale,
                    extra=sample.extra,
                )
            )
            publish_eval_log(run.id, f"[{idx}/{total}] scored {scores}")
        except Exception as exc:
            logger.warning(f"Sample #{idx} failed: {exc}")
            results.append(
                JudgeResult(
                    question=sample.question,
                    actual_answer="",
                    scores={k: 0 for k, _ in rubric},
                    rationale="",
                    error=str(exc),
                    extra=sample.extra,
                )
            )
            publish_eval_log(run.id, f"[{idx}/{total}] ERROR {exc}")

        progress_pct = int(idx / total * 100) if total else 100
        if progress_callback:
            progress_callback(idx, total)
        publish_eval_state(
            run.id, status="running", progress=progress_pct, done=idx, total=total
        )

    metrics = {
        key: (sum(values) / len(values) if values else 0.0)
        for key, values in aggregates.items()
    }
    metrics["overall"] = (
        sum(metrics[k] for k, _ in rubric) / max(len(rubric), 1)
    )

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
            "extra": r.extra,
        }
        for r in results
    ]
    persisted.status = BenchmarkStatus.COMPLETED
    persisted.completed_at = datetime.now(UTC)
    await session.commit()

    publish_eval_state(run.id, status="completed", progress=100, done=total, total=total)
    publish_eval_log(run.id, f"Eval complete: {metrics}")
    logger.info(f"Eval {run.id} complete: {metrics}")
    return run.id
