"""Amber operator TUI.

Skeleton with one screen per CLI domain. Each screen wraps the same service
calls used by the CLI commands; it is NOT a separate API surface.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Footer, Header, Static, Tab, TabbedContent, TabPane


class _PlaceholderPane(Static):
    """Minimal placeholder body until each domain screen is fleshed out."""

    DEFAULT_CSS = """
    _PlaceholderPane {
        padding: 1 2;
        color: $text-muted;
    }
    """


class AmberConsole(App):
    """Top-level operator TUI shell."""

    CSS = """
    Screen {
        layout: vertical;
    }
    TabbedContent {
        height: 1fr;
    }
    """

    TITLE = "Amber Operator Console"
    SUB_TITLE = "F4 skeleton — fill screens as features land"

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="backup"):
            with TabPane("Backup", id="backup"):
                yield _PlaceholderPane(
                    "Backup screen — TODO: list jobs (BackupJob), trigger create/restore, edit schedule.\n"
                    "Wire to: src.cli.commands.backup"
                )
            with TabPane("Tuning", id="tuning"):
                yield _PlaceholderPane(
                    "Tuning screen — TODO: prompt editor, retrieval params, per-tenant config viewer.\n"
                    "Wire to: src.cli.commands.tuning"
                )
            with TabPane("LLMs", id="llm"):
                yield _PlaceholderPane(
                    "LLM screen — TODO: default provider/model, per-step overrides, ollama url.\n"
                    "Wire to: src.cli.commands.llm"
                )
            with TabPane("Eval", id="eval"):
                yield _PlaceholderPane(
                    "Eval screen — TODO: pick framework (locomo/ragas), launch run, watch progress.\n"
                    "Wire to: src.cli.commands.eval"
                )
        yield Footer()


if __name__ == "__main__":  # pragma: no cover
    AmberConsole().run()
