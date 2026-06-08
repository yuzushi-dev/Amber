#!/usr/bin/env python3
"""Benchmark the sufficient-context iterative-retrieval loop: baseline vs loop.

Drives the live query API (the real production path) for a set of questions,
once with the sufficiency loop OFF and once ON, and scores each answer with the
LLM-as-judge :class:`JudgeService` (faithfulness + relevance). Also reports
retrieval coverage, sufficiency rounds, and latency.

The loop itself is product-agnostic; questions are supplied via ``--questions``
(a JSON list of strings). A small generic default set is used otherwise.

Usage (typically run inside the API container so service hosts resolve)::

    python3 scripts/benchmark_sufficiency.py \
        --base-url http://localhost:8000 \
        --api-key "$AMBER_API_KEY" \
        --questions /path/to/questions.json \
        --tenant default --max-chunks 5 --max-rounds 2

Cost: each question issues 2 API queries (answer generation) + up to 4 judge
LLM calls. No data is written; retrieval/generation are read-only.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.amber_platform.composition_root import configure_settings, get_settings  # noqa: E402
from src.api.config import settings as _settings  # noqa: E402
from src.core.admin_ops.application.evaluation.judge import JudgeService  # noqa: E402
from src.core.generation.application.registry import PromptRegistry  # noqa: E402
from src.core.generation.domain.ports.provider_factory import get_provider_factory  # noqa: E402
from src.core.generation.infrastructure.providers.factory import init_providers  # noqa: E402

DEFAULT_QUESTIONS = [
    "What are the prerequisites and the steps to install Acme Mail in a high-availability setup?",
    "Which Acme Mail components run on which nodes in a multi-server deployment, and what does each do?",
    "How do I prepare a server before installing Acme Mail, including package and repository prerequisites?",
    "What is the role of the database component in Acme Mail and how is it configured during installation?",
    "What monitoring components does Acme Mail provide and how are they installed and accessed?",
]


def _bootstrap_judge() -> JudgeService:
    configure_settings(_settings)
    s = get_settings()
    # Initialize the provider factory from settings (same mapping as api/main).
    init_providers(
        openai_api_key=s.openai_api_key,
        anthropic_api_key=s.anthropic_api_key,
        ollama_base_url=s.ollama_base_url,
        default_llm_provider=s.default_llm_provider,
        default_llm_model=s.default_llm_model,
        default_embedding_provider=s.default_embedding_provider,
        default_embedding_model=s.default_embedding_model,
        llm_fallback_local=s.llm_fallback_local,
        llm_fallback_economy=s.llm_fallback_economy,
        llm_fallback_standard=s.llm_fallback_standard,
        llm_fallback_premium=s.llm_fallback_premium,
        embedding_fallback_order=s.embedding_fallback_order,
        openrouter_api_key=s.openrouter_api_key,
        openrouter_base_url=s.openrouter_base_url,
        nvidia_nim_api_key=s.nvidia_nim_api_key,
        nvidia_nim_base_url=s.nvidia_nim_base_url,
        llm_fallback_enabled=s.llm_fallback_enabled,
        ollama_cloud_base_url=s.ollama_cloud_base_url,
        ollama_cloud_api_keys=s.ollama_cloud_api_keys,
    )
    # Best-effort DB config (usage logging); ignore if already configured.
    try:
        from src.core.database.session import configure_database

        configure_database(database_url=s.db.app_database_url or s.db.database_url)
    except Exception:
        pass
    provider = get_provider_factory().get_llm_provider()
    return JudgeService(llm=provider, prompt_registry=PromptRegistry())


async def _query(client, base_url, api_key, tenant, query, use_loop, max_chunks, max_rounds):
    body = {
        "query": query,
        "options": {
            "search_mode": "basic",
            "include_trace": True,
            "include_sources": True,
            "max_chunks": max_chunks,
            "use_sufficiency_loop": use_loop,
            "max_sufficiency_rounds": max_rounds,
        },
    }
    headers = {"X-API-Key": api_key, "X-Tenant-ID": tenant}
    t0 = time.perf_counter()
    r = await client.post(f"{base_url}/v1/query", json=body, headers=headers)
    lat = time.perf_counter() - t0
    r.raise_for_status()
    data = r.json()
    return data, lat


def _rounds(trace):
    return sum(1 for s in (trace or []) if s.get("step") == "sufficiency_check")


CORRECTNESS_PROMPT = """You are grading an AI answer against a reference (ground-truth) answer.
Score how well the AI answer captures the facts of the reference, ignoring style.

QUESTION: {query}

REFERENCE ANSWER:
{ideal}

AI ANSWER:
{answer}

Output exactly:
Score: <0.0-1.0>
Reasoning: <one short sentence>"""


async def _correctness(provider, query, ideal, answer):
    """Grade `answer` against the ground-truth `ideal` answer (0..1)."""
    prompt = CORRECTNESS_PROMPT.format(query=query, ideal=ideal, answer=answer)
    res = await provider.generate(prompt=prompt, temperature=0.0)
    for line in (res.text or "").splitlines():
        if line.lower().strip().startswith("score:"):
            try:
                return max(0.0, min(1.0, float(line.split(":", 1)[1].strip().split()[0])))
            except (ValueError, IndexError):
                return 0.0
    return 0.0


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--api-key", default=os.getenv("AMBER_API_KEY") or os.getenv("DEV_API_KEY", ""))
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--questions", default=None, help="JSON file: list of question strings")
    ap.add_argument("--golden", default=None,
                    help="JSON file: list of {query, ideal_answer} for ground-truth correctness")
    ap.add_argument("--max-chunks", type=int, default=5)
    ap.add_argument("--max-rounds", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("No API key. Pass --api-key or set AMBER_API_KEY / DEV_API_KEY.")

    # ideal[query] = ground-truth answer (golden mode) for correctness scoring.
    ideal: dict[str, str] = {}
    if args.golden:
        entries = json.load(open(args.golden))
        questions = [e["query"] for e in entries]
        ideal = {e["query"]: (e.get("ideal_answer") or "") for e in entries}
    elif args.questions:
        questions = json.load(open(args.questions))
    else:
        questions = DEFAULT_QUESTIONS

    judge = _bootstrap_judge()
    variants = [("OFF (baseline)", False), ("ON (loop)", True)]
    agg = {v: {"faith": [], "rel": [], "corr": [], "src": [], "docs": [], "rounds": [], "lat": []}
           for v, _ in variants}

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for qi, q in enumerate(questions, 1):
            print(f"\n### Q{qi}: {q[:70]}...")
            for label, use_loop in variants:
                data, lat = await _query(client, args.base_url, args.api_key, args.tenant,
                                         q, use_loop, args.max_chunks, args.max_rounds)
                sources = data.get("sources", []) or []
                ctx = "\n\n".join(s.get("text", "") for s in sources)
                ans = data.get("answer", "")
                rounds = _rounds(data.get("trace"))
                ndocs = len({s.get("document_id") for s in sources})

                f = await judge.evaluate_faithfulness(query=q, context=ctx, answer=ans)
                rel = await judge.evaluate_relevance(query=q, answer=ans)
                corr = None
                if ideal.get(q):
                    corr = await _correctness(judge.llm, q, ideal[q], ans)

                a = agg[label]
                a["faith"].append(f.score)
                a["rel"].append(rel.score)
                if corr is not None:
                    a["corr"].append(corr)
                a["src"].append(len(sources))
                a["docs"].append(ndocs)
                a["rounds"].append(rounds)
                a["lat"].append(lat)
                cstr = f" corr={corr:.2f}" if corr is not None else ""
                print(f"  {label:16s} faith={f.score:.2f} rel={rel.score:.2f}{cstr} "
                      f"sources={len(sources)} docs={ndocs} rounds={rounds} lat={lat:.1f}s")

    def m(xs):
        return statistics.mean(xs) if xs else 0.0

    print("\n" + "=" * 80)
    print(f"BENCHMARK (n={len(questions)}, max_chunks={args.max_chunks}, max_rounds={args.max_rounds})")
    print("=" * 80)
    print(f"{'variant':<16} {'faith':>7} {'relev':>7} {'correct':>8} {'docs':>6} {'sources':>8} {'rounds':>7} {'lat_s':>7}")
    print("-" * 80)
    for label, _ in variants:
        a = agg[label]
        corr = f"{m(a['corr']):>8.3f}" if a["corr"] else f"{'n/a':>8}"
        print(f"{label:<16} {m(a['faith']):>7.3f} {m(a['rel']):>7.3f} {corr} {m(a['docs']):>6.2f} "
              f"{m(a['src']):>8.2f} {m(a['rounds']):>7.2f} {m(a['lat']):>7.1f}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
