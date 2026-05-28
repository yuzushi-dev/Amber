"""Amber CLI root."""

from __future__ import annotations

import typer

from src.cli.commands import backup as backup_cmd
from src.cli.commands import eval as eval_cmd
from src.cli.commands import llm as llm_cmd
from src.cli.commands import tui as tui_cmd
from src.cli.commands import tuning as tuning_cmd

app = typer.Typer(
    name="amber",
    help="Amber operator CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(backup_cmd.app, name="backup", help="Create, list, restore and schedule backups")
app.add_typer(tuning_cmd.app, name="tuning", help="System prompts and retrieval parameters")
app.add_typer(llm_cmd.app, name="llm", help="LLM and embedding provider/model settings")
app.add_typer(eval_cmd.app, name="eval", help="Evaluation runs (Locomo and friends)")
app.add_typer(tui_cmd.app, name="tui", help="Interactive operator console (Textual TUI)")


if __name__ == "__main__":
    app()
