"""
Locomo adapter
==============

Projects the official Locomo dataset format (one JSON file with ``sessions``
and ``qa`` arrays) into ``JudgeSample`` instances + extended rubric.

The Locomo JSON shape we support::

    {
      "sessions": [
        {"session_id": "S1", "date": "2024-03-04", "dialog": [
            {"speaker": "Alice", "text": "..."},
            {"speaker": "Bob",   "text": "..."}
        ]},
        ...
      ],
      "qa": [
        {
          "question": "...",
          "answer": "...",                # ground truth
          "category": "single_session",
          "evidence": ["S1"]              # session_id list, optional
        },
        ...
      ]
    }

If ``evidence`` is missing, the adapter falls back to "all sessions" so the
judge still receives some context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.admin_ops.application.evaluation.judge_eval import JudgeSample

# Extended rubric for Locomo. Order matters — it's reused as JSON keys.
LOCOMO_RUBRIC: list[tuple[str, str]] = [
    ("relevance", "Does the answer address the question directly?"),
    ("faithfulness", "Is the answer grounded in retrieved/given context (no hallucination)?"),
    ("completeness", "Does the answer cover the key points of the ground-truth answer?"),
    (
        "temporal_consistency",
        "Is the answer consistent with the dates and ordering of the evidence sessions?",
    ),
    (
        "memory_recall",
        "Does the answer correctly recall events from the evidence sessions?",
    ),
]


def _session_block(session: dict[str, Any]) -> str:
    date = session.get("date") or "?"
    sid = session.get("session_id") or "?"
    lines = [f"[{sid} · {date}]"]
    for turn in session.get("dialog", []):
        speaker = turn.get("speaker", "?")
        text = turn.get("text") or turn.get("utterance") or ""
        lines.append(f"  {speaker}: {text}")
    return "\n".join(lines)


def load_locomo(path: Path) -> list[JudgeSample]:
    """Load a Locomo JSON file and project it to JudgeSample[]."""
    data = json.loads(path.read_text(encoding="utf-8"))
    sessions = {s.get("session_id"): s for s in data.get("sessions", []) if s.get("session_id")}
    all_sessions_text = "\n\n".join(_session_block(s) for s in data.get("sessions", []))

    samples: list[JudgeSample] = []
    for entry in data.get("qa", []):
        question = entry.get("question") or ""
        answer = entry.get("answer") or entry.get("expected_answer") or ""
        evidence_ids = entry.get("evidence") or []

        if evidence_ids:
            context_parts: list[str] = []
            for sid in evidence_ids:
                session = sessions.get(sid)
                if session:
                    context_parts.append(_session_block(session))
            context = "\n\n".join(context_parts) if context_parts else all_sessions_text
        else:
            context = all_sessions_text

        samples.append(
            JudgeSample(
                question=question,
                expected_answer=answer,
                ground_truth_context=context,
                extra={
                    "category": entry.get("category"),
                    "evidence_ids": evidence_ids,
                },
            )
        )
    return samples
