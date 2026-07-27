"""Amber operator TUI."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Button, Footer, Header, TabbedContent, TabPane

from src.cli.tui.screens import BackupScreen, EvalScreen, LlmScreen, TuningScreen


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
    SUB_TITLE = "Backup · Tuning · LLMs · Eval"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="backup"):
            with TabPane("Backup", id="backup"):
                yield BackupScreen()
            with TabPane("Tuning", id="tuning"):
                yield TuningScreen()
            with TabPane("LLMs", id="llm"):
                yield LlmScreen()
            with TabPane("Eval", id="eval"):
                yield EvalScreen()
        yield Footer()

    async def action_refresh(self) -> None:
        """Forward 'r' to the active tab's refresh button if it has one."""
        try:
            tabs = self.query_one(TabbedContent)
            active = tabs.active
        except Exception:
            return
        button_id = {
            "backup": "refresh",
            "tuning": "load-prompt",
            "llm": "llm-refresh",
            "eval": "eval-refresh",
        }.get(active)
        if not button_id:
            return
        try:
            btn = self.query_one(f"#{button_id}", Button)
            btn.press()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover
    AmberConsole().run()
