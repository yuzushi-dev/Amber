"""Evaluation CLI.

Replaces the ad-hoc RAGAS UI. Stage 1: list/inspect existing benchmark
runs that may still live in the database. Stage 2 (Locomo or equivalent)
is tracked separately and will land here once the methodology is chosen.
"""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("list-frameworks")
def list_frameworks() -> None:
    """Print the evaluation frameworks currently wired in."""
    console.print(
        "[bold]Available[/bold]\n"
        "  - ragas       legacy benchmark runner (deprecated UI, still callable)\n"
        "\n"
        "[bold]Planned (F4b)[/bold]\n"
        "  - locomo      conversational long-context evaluation\n"
        "  - custom      user-defined rubric + LLM-as-judge\n"
    )


@app.command("ragas-run")
def ragas_run(
    dataset: str = typer.Argument(..., help="Dataset file under data/ragas/"),
    tenant_id: str = typer.Option("default"),
) -> None:
    """Dispatch a legacy ragas benchmark run (worker queue)."""
    try:
        from src.workers.tasks import run_ragas_benchmark  # type: ignore
    except ImportError as exc:  # ragas extras may be uninstalled
        raise typer.Exit(
            "ragas worker task not available; install optional extras first"
        ) from exc

    result = run_ragas_benchmark.delay(dataset, tenant_id=tenant_id)
    console.print(f"[green]Queued[/green] task_id={result.id} dataset={dataset}")


@app.command("design")
def design() -> None:
    """Print the design notes for the new evaluation framework."""
    console.print(
        "Evaluation roadmap is documented in docs/cli-tui-design.md (section 'F4b — Evaluation')."
    )
