"""
Evaluation Runner
=================

Runs every golden-dataset query through an injected answerer and asks
JudgeService to score the actual answer against the actual retrieved chunks.

The production answerer (retrieval + generation wired like POST /query) lives
in the CLI, because wiring the composition root is not allowed from core:

    amber eval golden-run --tenant-id <tenant>

Per-item outcome (``status``):
- ``scored``: answer and contexts judged for faithfulness and relevance.
- ``no_retrieval``: no chunks came back; not judged (a canned "no info" answer
  would look faithful to an empty context and inflate the score).
- ``error``: the answerer or the judge raised; recorded and skipped.
Averages are computed over ``scored`` items only (``None`` when there are none).
"""

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.core.admin_ops.application.evaluation.judge import JudgeService
from src.core.generation.application.registry import PromptRegistry
from src.core.generation.domain.ports.provider_factory import (
    build_provider_factory,
    get_provider_factory,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = Path(__file__).with_name("golden_dataset.json")

# (query, tenant_id) -> (answer, full contents of the retrieved chunks)
AnswerFn = Callable[[str, str], Awaitable[tuple[str, list[str]]]]


def _average(results: list[dict[str, Any]], key: str) -> float | None:
    scores = [r[key] for r in results if r["status"] == "scored"]
    return sum(scores) / len(scores) if scores else None


async def run_evaluation(
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    provider_name: str = "openai",
    tenant_id: str = "default",
    *,
    answer_fn: AnswerFn,
    judge: Any = None,
) -> list[dict[str, Any]]:
    """Run each golden-dataset query through ``answer_fn`` and judge the output."""
    with open(dataset_path) as f:
        dataset = json.load(f)

    if judge is None:
        try:
            factory = build_provider_factory()
        except RuntimeError:
            factory = get_provider_factory()
        judge = JudgeService(llm=factory.get_llm_provider(provider_name), prompt_registry=PromptRegistry())

    results: list[dict[str, Any]] = []
    print(f"\n--- Starting Evaluation on {len(dataset)} items (tenant {tenant_id}) ---\n")

    for i, entry in enumerate(dataset):
        query = entry["query"]
        print(f"[{i + 1}/{len(dataset)}] Evaluating Query: {query}")
        try:
            answer, contexts = await answer_fn(query, tenant_id)
            if not contexts:
                results.append({"query": query, "status": "no_retrieval", "answer": answer})
                continue
            context = "\n\n".join(contexts)
            faith_res = await judge.evaluate_faithfulness(query=query, context=context, answer=answer)
            rel_res = await judge.evaluate_relevance(query=query, answer=answer)
        except Exception as e:
            logger.exception("Evaluation failed for query %r", query)
            results.append({"query": query, "status": "error", "error": str(e)})
            continue

        results.append(
            {
                "query": query,
                "status": "scored",
                "answer": answer,
                "contexts_count": len(contexts),
                "faithfulness": faith_res.score,
                "relevance": rel_res.score,
                "reasoning_faith": faith_res.reasoning,
                "reasoning_rel": rel_res.reasoning,
            }
        )

    counts = {s: sum(r["status"] == s for r in results) for s in ("scored", "no_retrieval", "error")}
    avg_faith, avg_rel = _average(results, "faithfulness"), _average(results, "relevance")

    print("\n--- Evaluation Summary ---")
    print(f"Scored: {counts['scored']}  No retrieval: {counts['no_retrieval']}  Errors: {counts['error']}")
    print(f"Average Faithfulness: {'n/a' if avg_faith is None else f'{avg_faith:.2f}'}")
    print(f"Average Relevance: {'n/a' if avg_rel is None else f'{avg_rel:.2f}'}")
    print("--------------------------\n")

    return results
