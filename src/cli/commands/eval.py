"""Evaluation CLI: ragas (legacy) and LLM-as-judge (F4b)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from sqlalchemy import desc, select

from src.cli._session import run, session_scope

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("list-frameworks")
def list_frameworks() -> None:
    """List evaluation frameworks available in this build."""
    console.print(
        "[bold]Frameworks[/bold]\n"
        "  - ragas       legacy ragas runner (worker task)\n"
        "  - judge       LLM-as-judge end-to-end (CLI driver below)\n"
        "  - locomo      [yellow]planned[/yellow] long-context conversational eval\n"
    )


@app.command("ragas-run")
def ragas_run(
    dataset: str = typer.Argument(...),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Dispatch a legacy ragas benchmark run via Celery."""
    try:
        from src.workers.tasks import run_ragas_benchmark  # type: ignore
    except ImportError as exc:
        raise typer.Exit(
            "ragas worker task not available; install optional extras first"
        ) from exc

    result = run_ragas_benchmark.delay(dataset, tenant_id=tenant_id)
    console.print(f"[green]Queued[/green] task_id={result.id} dataset={dataset}")


@app.command("judge-run")
def judge_run(
    dataset: Path = typer.Argument(..., exists=True, readable=True, help="JSONL dataset"),
    tenant_id: str = typer.Option("default"),
    judge_provider: str = typer.Option("openai", help="Provider for the judge model"),
    judge_model: str = typer.Option("gpt-4o-mini", help="Judge model id"),
    api_base: str = typer.Option(
        "http://localhost:8000/api/v1",
        help="Base URL of the Amber API used by the answerer",
    ),
    api_key: str | None = typer.Option(
        None,
        envvar="AMBER_API_KEY",
        help="API key for the answerer (Bearer). Required unless --mock-answers.",
    ),
    mock_answers: bool = typer.Option(
        False,
        "--mock-answers",
        help="Use the expected_answer as the actual answer (smoke-test the judge).",
    ),
) -> None:
    """Run an end-to-end LLM-as-judge evaluation against a JSONL dataset."""
    from src.core.admin_ops.application.evaluation.judge_eval import (
        JudgeSample,
        run_judge_evaluation,
    )
    from src.core.generation.domain.ports.provider_factory import get_provider_factory

    if not mock_answers and not api_key:
        raise typer.BadParameter("--api-key required (or set AMBER_API_KEY) unless --mock-answers")

    async def _answerer_real(client: httpx.AsyncClient, question: str) -> str:
        response = await client.post(
            f"{api_base}/chat",
            json={"query": question, "stream": False},
            timeout=120.0,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("response") or payload.get("answer") or ""

    async def _orchestrate() -> str:
        factory = get_provider_factory()
        judge = factory.get_llm_provider(provider_name=judge_provider, model=judge_model)

        async def _judge_caller(system_prompt: str, user_prompt: str) -> str:
            result = await judge.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=judge_model,
                temperature=0.0,
            )
            return result.text

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=False,
        ) as bar:
            task_id = bar.add_task("Evaluating", total=1)

            def _cb(done: int, total: int) -> None:
                bar.update(task_id, total=total, completed=done)

            if mock_answers:
                async def _answerer(sample: JudgeSample) -> str:
                    return sample.expected_answer

                async with session_scope() as session:
                    return await run_judge_evaluation(
                        session,
                        dataset_path=dataset,
                        tenant_id=tenant_id,
                        judge_provider_name=judge_provider,
                        judge_model=judge_model,
                        answerer=_answerer,
                        judge_caller=_judge_caller,
                        progress_callback=_cb,
                    )

            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            async with httpx.AsyncClient(headers=headers) as client:
                async def _answerer(sample: JudgeSample) -> str:
                    return await _answerer_real(client, sample.question)

                async with session_scope() as session:
                    return await run_judge_evaluation(
                        session,
                        dataset_path=dataset,
                        tenant_id=tenant_id,
                        judge_provider_name=judge_provider,
                        judge_model=judge_model,
                        answerer=_answerer,
                        judge_caller=_judge_caller,
                        progress_callback=_cb,
                    )

    run_id = asyncio.run(_orchestrate())
    console.print(f"[green]Eval complete[/green] run_id=[cyan]{run_id}[/cyan]")


@app.command("locomo-run")
def locomo_run(
    dataset: Path = typer.Argument(
        ..., exists=True, readable=True, help="Locomo JSON file (sessions + qa)"
    ),
    tenant_id: str = typer.Option("default"),
    judge_provider: str = typer.Option("openai"),
    judge_model: str = typer.Option("gpt-4o-mini"),
    api_base: str = typer.Option("http://localhost:8000/api/v1"),
    api_key: str | None = typer.Option(None, envvar="AMBER_API_KEY"),
    mock_answers: bool = typer.Option(False, "--mock-answers"),
) -> None:
    """Run a Locomo benchmark (long-context conversational, 5-criterion rubric)."""
    from src.core.admin_ops.application.evaluation.judge_eval import (
        JudgeSample,
        run_judge_evaluation,
    )
    from src.core.admin_ops.application.evaluation.locomo_adapter import (
        LOCOMO_RUBRIC,
        load_locomo,
    )
    from src.core.generation.domain.ports.provider_factory import get_provider_factory

    if not mock_answers and not api_key:
        raise typer.BadParameter("--api-key required (or set AMBER_API_KEY) unless --mock-answers")

    samples = load_locomo(dataset)
    if not samples:
        raise typer.BadParameter("Locomo dataset produced 0 samples")

    async def _answerer_real(client: httpx.AsyncClient, question: str) -> str:
        response = await client.post(
            f"{api_base}/chat", json={"query": question, "stream": False}, timeout=120.0
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("response") or payload.get("answer") or ""

    async def _orchestrate() -> str:
        factory = get_provider_factory()
        judge = factory.get_llm_provider(provider_name=judge_provider, model=judge_model)

        async def _judge_caller(system_prompt: str, user_prompt: str) -> str:
            result = await judge.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=judge_model,
                temperature=0.0,
            )
            return result.text

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=False,
        ) as bar:
            task_id = bar.add_task("Locomo eval", total=len(samples))

            def _cb(done: int, total: int) -> None:
                bar.update(task_id, total=total, completed=done)

            if mock_answers:
                async def _answerer(sample: JudgeSample) -> str:
                    return sample.expected_answer

                async with session_scope() as session:
                    return await run_judge_evaluation(
                        session,
                        samples=samples,
                        dataset_path=dataset,
                        tenant_id=tenant_id,
                        judge_provider_name=judge_provider,
                        judge_model=judge_model,
                        answerer=_answerer,
                        judge_caller=_judge_caller,
                        rubric=LOCOMO_RUBRIC,
                        framework="locomo",
                        progress_callback=_cb,
                    )

            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            async with httpx.AsyncClient(headers=headers) as client:
                async def _answerer(sample: JudgeSample) -> str:
                    return await _answerer_real(client, sample.question)

                async with session_scope() as session:
                    return await run_judge_evaluation(
                        session,
                        samples=samples,
                        dataset_path=dataset,
                        tenant_id=tenant_id,
                        judge_provider_name=judge_provider,
                        judge_model=judge_model,
                        answerer=_answerer,
                        judge_caller=_judge_caller,
                        rubric=LOCOMO_RUBRIC,
                        framework="locomo",
                        progress_callback=_cb,
                    )

    run_id = asyncio.run(_orchestrate())
    console.print(f"[green]Locomo eval complete[/green] run_id=[cyan]{run_id}[/cyan]")


@app.command("list-runs")
def list_runs(
    framework: str | None = typer.Option(None, help="Filter by framework (ragas|judge|locomo)"),
    tenant_id: str = typer.Option("default"),
    limit: int = typer.Option(20),
) -> None:
    """Show recent benchmark runs."""
    from src.core.admin_ops.domain.benchmark_run import BenchmarkRun

    async def _query() -> list[BenchmarkRun]:
        async with session_scope() as session:
            stmt = select(BenchmarkRun).where(BenchmarkRun.tenant_id == tenant_id)
            if framework:
                stmt = stmt.where(BenchmarkRun.framework == framework)
            stmt = stmt.order_by(desc(BenchmarkRun.created_at)).limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    rows = run(_query())

    table = Table(title=f"Benchmark runs — tenant {tenant_id}")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Framework")
    table.add_column("Dataset")
    table.add_column("Status")
    table.add_column("Overall")
    table.add_column("Created")
    for r in rows:
        status_v = r.status.value if r.status else "?"
        overall = ""
        if r.metrics and isinstance(r.metrics, dict) and "overall" in r.metrics:
            overall = f"{float(r.metrics['overall']):.2f}"
        created = r.created_at.isoformat() if r.created_at else "-"
        table.add_row(r.id[:8], r.framework or "?", r.dataset_name, status_v, overall, created)
    console.print(table)


def _load_run(run_id: str) -> dict[str, Any]:
    from src.core.admin_ops.domain.benchmark_run import BenchmarkRun

    async def _query() -> dict[str, Any]:
        async with session_scope() as session:
            res = await session.execute(
                select(BenchmarkRun).where(BenchmarkRun.id.like(f"{run_id}%"))
            )
            row = res.scalar_one_or_none()
            if not row:
                raise typer.BadParameter(f"Run {run_id} not found")
            return {
                "id": row.id,
                "framework": row.framework,
                "dataset": row.dataset_name,
                "status": row.status.value if row.status else "?",
                "metrics": row.metrics or {},
                "details": row.details or [],
                "config": row.config or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "error_message": row.error_message,
            }

    return run(_query())


@app.command("show")
def show_run(
    run_id: str = typer.Argument(..., help="Run ID (prefix is enough)"),
    full: bool = typer.Option(False, "--full", help="Print per-sample details too"),
) -> None:
    """Inspect a benchmark run."""
    data = _load_run(run_id)

    console.print(f"[bold]Run[/bold] {data['id']}  framework={data['framework']}  status={data['status']}")
    console.print(f"  dataset={data['dataset']}")
    console.print(f"  created={data['created_at']}  completed={data['completed_at']}")
    if data["metrics"]:
        table = Table(title="Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Score")
        for k, v in data["metrics"].items():
            table.add_row(k, f"{float(v):.3f}" if isinstance(v, (int, float)) else str(v))
        console.print(table)

    if full and data["details"]:
        for idx, d in enumerate(data["details"], start=1):
            console.print(f"\n[bold]Sample {idx}[/bold]: {d.get('question', '')[:120]}")
            console.print(f"  scores={d.get('scores')}")
            if d.get("error"):
                console.print(f"  [red]error[/red]: {d['error']}")


@app.command("compare")
def compare_runs(
    run_a: str = typer.Argument(...),
    run_b: str = typer.Argument(...),
) -> None:
    """Side-by-side comparison of two runs by aggregate metric."""
    a = _load_run(run_a)
    b = _load_run(run_b)

    keys = sorted(set(a["metrics"].keys()) | set(b["metrics"].keys()))
    table = Table(title=f"Compare {a['id'][:8]} vs {b['id'][:8]}")
    table.add_column("Metric", style="cyan")
    table.add_column(f"A ({a['framework']})")
    table.add_column(f"B ({b['framework']})")
    table.add_column("Δ (B-A)")
    for key in keys:
        va = a["metrics"].get(key)
        vb = b["metrics"].get(key)
        delta = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            d = vb - va
            color = "green" if d >= 0 else "red"
            delta = f"[{color}]{d:+.3f}[/{color}]"
        table.add_row(
            key,
            f"{float(va):.3f}" if isinstance(va, (int, float)) else "-",
            f"{float(vb):.3f}" if isinstance(vb, (int, float)) else "-",
            delta,
        )
    console.print(table)


@app.command("report")
def report(
    run_id: str = typer.Argument(...),
    fmt: str = typer.Option("md", "--format", "-f", help="md | json | csv"),
    out: Path | None = typer.Option(None, "--out", help="Write to file"),
) -> None:
    """Export a run as markdown / json / csv."""
    data = _load_run(run_id)
    fmt = fmt.lower()

    if fmt == "json":
        body = json.dumps(data, indent=2, default=str)
    elif fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["question", *[k for k, _ in _rubric_keys(data)], "error"])
        for d in data["details"]:
            writer.writerow(
                [
                    d.get("question", ""),
                    *[d.get("scores", {}).get(k, "") for k, _ in _rubric_keys(data)],
                    d.get("error", ""),
                ]
            )
        body = buf.getvalue()
    else:  # md
        lines = [
            f"# Eval report — {data['id']}",
            f"- framework: **{data['framework']}**",
            f"- dataset: `{data['dataset']}`",
            f"- status: {data['status']}",
            f"- created: {data['created_at']}",
            "",
            "## Metrics",
            "",
            "| metric | score |",
            "|---|---|",
        ]
        for k, v in data["metrics"].items():
            score = f"{float(v):.3f}" if isinstance(v, (int, float)) else str(v)
            lines.append(f"| {k} | {score} |")
        lines.append("")
        lines.append(f"## Samples ({len(data['details'])})")
        for idx, d in enumerate(data["details"], start=1):
            lines.append(f"### {idx}. {d.get('question', '')[:120]}")
            lines.append(f"- scores: `{d.get('scores')}`")
            if d.get("error"):
                lines.append(f"- error: {d['error']}")
            if d.get("rationale"):
                lines.append(f"- rationale: {d['rationale']}")
            lines.append("")
        body = "\n".join(lines)

    if out:
        out.write_text(body, encoding="utf-8")
        console.print(f"[green]Wrote[/green] {out}")
    else:
        console.print(body)


def _rubric_keys(data: dict[str, Any]) -> list[tuple[str, str]]:
    config = data.get("config") or {}
    rubric = config.get("rubric")
    if isinstance(rubric, list):
        return [(item.get("name", ""), item.get("description", "")) for item in rubric]
    return [("relevance", ""), ("faithfulness", ""), ("completeness", "")]


# Suppress unused-import nag in narrow envs
_ = os
