"""Interactive Textual TUI entry point."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)
console = Console()


@app.callback()
def launch() -> None:
    """Open the operator TUI. Lazy-imports Textual so the rest of the CLI works without it."""
    try:
        from src.cli.tui.app import AmberConsole  # noqa: WPS433 (deferred import)
    except ImportError as exc:  # pragma: no cover
        raise typer.Exit(
            "Textual is not installed. Run: uv sync --extra dev or pip install textual"
        ) from exc

    AmberConsole().run()
