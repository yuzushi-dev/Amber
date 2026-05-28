"""Concrete TUI screens. Keep widgets thin; delegate to src.cli.tui.data and CLI cmds."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
    TextArea,
)

from src.cli.tui import data as tui_data

DEFAULT_TENANT = "default"


# ============================================================================
# Backup
# ============================================================================


class BackupScreen(Vertical):
    """List jobs + create + restore + schedule."""

    DEFAULT_CSS = """
    BackupScreen {
        padding: 1 2;
    }
    BackupScreen Horizontal.actions {
        height: auto;
        margin-bottom: 1;
    }
    BackupScreen Horizontal.actions Button {
        margin-right: 1;
    }
    BackupScreen .schedule {
        padding: 1;
        border: solid $accent;
        margin-top: 1;
    }
    BackupScreen .schedule Horizontal {
        height: auto;
        margin-bottom: 1;
    }
    BackupScreen .schedule Label {
        width: 16;
    }
    """

    backups: reactive[list[dict[str, Any]]] = reactive(list)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="actions"):
            yield Button("Refresh", id="refresh", variant="primary")
            yield Button("Create user_data", id="create-user")
            yield Button("Create full_system", id="create-full")
            yield Button("Restore (merge)", id="restore-merge")
            yield Button("Restore (replace)", id="restore-replace", variant="error")

        yield DataTable(id="backups-table", zebra_stripes=True, cursor_type="row")

        with Vertical(classes="schedule"):
            yield Label("[b]Schedule[/b]")
            with Horizontal():
                yield Label("Enabled")
                yield Switch(id="sched-enabled", value=False)
            with Horizontal():
                yield Label("Frequency")
                yield Select(
                    [("daily", "daily"), ("weekly", "weekly")],
                    id="sched-frequency",
                    value="daily",
                    allow_blank=False,
                )
            with Horizontal():
                yield Label("Time (UTC)")
                yield Input(value="02:00", id="sched-time", placeholder="HH:MM")
            with Horizontal():
                yield Label("Scope")
                yield Select(
                    [("user_data", "user_data"), ("full_system", "full_system")],
                    id="sched-scope",
                    value="user_data",
                    allow_blank=False,
                )
            with Horizontal():
                yield Label("Retention")
                yield Input(value="7", id="sched-retention", placeholder="N")
            with Horizontal():
                yield Button("Save schedule", id="sched-save", variant="success")

    async def on_mount(self) -> None:
        table = self.query_one("#backups-table", DataTable)
        table.add_columns("ID", "Scope", "Status", "Size (KB)", "Created", "Scheduled")
        await self._refresh()

    async def _refresh(self) -> None:
        rows = await tui_data.list_backups(DEFAULT_TENANT)
        self.backups = rows
        table = self.query_one("#backups-table", DataTable)
        table.clear()
        for r in rows:
            size_kb = f"{r['file_size'] / 1024:.1f}" if r["file_size"] else "-"
            table.add_row(
                r["id"][:8],
                r["scope"],
                r["status"],
                size_kb,
                r["created_at"],
                "yes" if r["is_scheduled"] else "no",
                key=r["id"],
            )

        sched = await tui_data.get_schedule(DEFAULT_TENANT)
        if sched:
            self.query_one("#sched-enabled", Switch).value = sched["enabled"]
            self.query_one("#sched-frequency", Select).value = sched["frequency"]
            self.query_one("#sched-time", Input).value = sched["time_utc"]
            self.query_one("#sched-scope", Select).value = sched["scope"]
            self.query_one("#sched-retention", Input).value = str(sched["retention_count"])

    def _selected_id(self) -> str | None:
        table = self.query_one("#backups-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        row_keys = list(table.rows.keys())
        if not row_keys:
            return None
        key = row_keys[table.cursor_row]
        return str(key.value) if key else None

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "refresh":
            await self._refresh()
        elif bid in ("create-user", "create-full"):
            scope = "user_data" if bid == "create-user" else "full_system"
            await self._dispatch_create(scope)
            await self._refresh()
        elif bid in ("restore-merge", "restore-replace"):
            mode = "merge" if bid == "restore-merge" else "replace"
            sel = self._selected_id()
            if not sel:
                self.app.notify("Select a backup row first", severity="warning")
                return
            await self._dispatch_restore(sel, mode)
        elif bid == "sched-save":
            await self._save_schedule()
            await self._refresh()

    async def _dispatch_create(self, scope: str) -> None:
        from src.core.admin_ops.domain.backup_job import (
            BackupJob,
            BackupScope,
            BackupStatus,
        )
        from src.workers.backup_tasks import create_backup as create_backup_task

        from src.cli._session import session_scope

        job_id = str(uuid4())
        async with session_scope() as session:
            session.add(
                BackupJob(
                    id=job_id,
                    tenant_id=DEFAULT_TENANT,
                    scope=BackupScope(scope),
                    status=BackupStatus.PENDING,
                )
            )
            await session.commit()
        create_backup_task.delay(job_id, DEFAULT_TENANT, scope)
        self.app.notify(f"Queued backup {job_id[:8]} ({scope})")

    async def _dispatch_restore(self, backup_id: str, mode: str) -> None:
        from sqlalchemy import select

        from src.cli._session import session_scope
        from src.core.admin_ops.domain.backup_job import (
            BackupJob,
            BackupStatus,
            RestoreJob,
            RestoreMode,
        )
        from src.workers.backup_tasks import restore_backup as restore_backup_task

        async with session_scope() as session:
            res = await session.execute(
                select(BackupJob)
                .where(BackupJob.id == backup_id)
                .where(BackupJob.tenant_id == DEFAULT_TENANT)
            )
            backup = res.scalar_one_or_none()
            if not backup or backup.status != BackupStatus.COMPLETED or not backup.result_path:
                self.app.notify("Backup not ready for restore", severity="error")
                return
            job_id = str(uuid4())
            session.add(
                RestoreJob(
                    id=job_id,
                    tenant_id=DEFAULT_TENANT,
                    backup_job_id=backup_id,
                    mode=RestoreMode(mode),
                    status=BackupStatus.PENDING,
                )
            )
            await session.commit()
            backup_path = backup.result_path
        restore_backup_task.delay(job_id, DEFAULT_TENANT, backup_path, mode)
        self.app.notify(f"Restore queued ({mode})")

    async def _save_schedule(self) -> None:
        from sqlalchemy import select

        from src.cli._session import session_scope
        from src.core.admin_ops.domain.backup_job import BackupSchedule, BackupScope

        enabled = self.query_one("#sched-enabled", Switch).value
        frequency = str(self.query_one("#sched-frequency", Select).value)
        time_utc = self.query_one("#sched-time", Input).value
        scope_value = str(self.query_one("#sched-scope", Select).value)
        try:
            retention = int(self.query_one("#sched-retention", Input).value)
        except ValueError:
            self.app.notify("Retention must be an integer", severity="error")
            return

        try:
            scope_enum = BackupScope(scope_value)
        except ValueError:
            self.app.notify(f"Invalid scope: {scope_value}", severity="error")
            return

        async with session_scope() as session:
            res = await session.execute(
                select(BackupSchedule).where(BackupSchedule.tenant_id == DEFAULT_TENANT)
            )
            row = res.scalar_one_or_none()
            if row:
                row.enabled = enabled
                row.frequency = frequency
                row.time_utc = time_utc
                row.scope = scope_enum
                row.retention_count = retention
            else:
                session.add(
                    BackupSchedule(
                        id=str(uuid4()),
                        tenant_id=DEFAULT_TENANT,
                        enabled=enabled,
                        frequency=frequency,
                        time_utc=time_utc,
                        scope=scope_enum,
                        retention_count=retention,
                    )
                )
            await session.commit()
        self.app.notify("Schedule saved")


# ============================================================================
# Tuning
# ============================================================================


PROMPT_FIELDS = [
    "rag_system_prompt",
    "rag_user_prompt",
    "agent_system_prompt",
    "community_summary_prompt",
    "fact_extraction_prompt",
]


class TuningScreen(Vertical):
    """Prompt editor + freeform field editor."""

    DEFAULT_CSS = """
    TuningScreen {
        padding: 1 2;
    }
    TuningScreen Horizontal.row {
        height: auto;
        margin-bottom: 1;
    }
    TuningScreen TextArea {
        height: 1fr;
        min-height: 12;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(classes="row"):
            yield Label("Prompt")
            yield Select(
                [(f, f) for f in PROMPT_FIELDS],
                id="prompt-field",
                value=PROMPT_FIELDS[0],
                allow_blank=False,
            )
            yield Button("Load", id="load-prompt", variant="primary")
            yield Button("Save", id="save-prompt", variant="success")
            yield Button("Reset (drop override)", id="reset-prompt", variant="error")
        yield TextArea(id="prompt-text", language="markdown")

    async def on_mount(self) -> None:
        await self._load()

    async def _load(self) -> None:
        field = str(self.query_one("#prompt-field", Select).value)
        config = await tui_data.load_tenant_config(DEFAULT_TENANT)
        value = config.get(field) or ""
        self.query_one("#prompt-text", TextArea).text = value if isinstance(value, str) else json.dumps(value)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "load-prompt":
            await self._load()
        elif bid == "save-prompt":
            field = str(self.query_one("#prompt-field", Select).value)
            text = self.query_one("#prompt-text", TextArea).text
            await tui_data.save_tenant_field(DEFAULT_TENANT, field, text)
            self.app.notify(f"Saved {field}")
        elif bid == "reset-prompt":
            field = str(self.query_one("#prompt-field", Select).value)
            await tui_data.save_tenant_field(DEFAULT_TENANT, field, None)
            self.app.notify(f"Cleared override {field}")
            await self._load()


# ============================================================================
# LLM
# ============================================================================


class LlmScreen(Vertical):
    """Defaults + per-step overrides matrix (read-mostly, edit via CLI)."""

    DEFAULT_CSS = """
    LlmScreen {
        padding: 1 2;
    }
    LlmScreen Horizontal.row {
        height: auto;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(classes="row"):
            yield Button("Refresh", id="llm-refresh", variant="primary")
            yield Label("Defaults: ")
            yield Static("—", id="llm-defaults")
        yield Static("[i]Per-step overrides[/i]")
        yield DataTable(id="llm-steps", zebra_stripes=True, cursor_type="row")

    async def on_mount(self) -> None:
        table = self.query_one("#llm-steps", DataTable)
        table.add_columns("Step", "Provider", "Model", "Temp", "Seed")
        await self._refresh()

    async def _refresh(self) -> None:
        config = await tui_data.load_tenant_config(DEFAULT_TENANT)
        defaults_text = (
            f"{config.get('llm_provider', '—')} / {config.get('llm_model', '—')} "
            f"(T={config.get('temperature', '—')}, seed={config.get('seed', '—')})"
        )
        self.query_one("#llm-defaults", Static).update(defaults_text)

        table = self.query_one("#llm-steps", DataTable)
        table.clear()
        steps = config.get("llm_steps") or {}
        if not steps:
            table.add_row("(no per-step overrides — edit via amber llm set-step)", "", "", "", "")
            return
        for step_id, override in steps.items():
            table.add_row(
                step_id,
                str(override.get("provider", "—")),
                str(override.get("model", "—")),
                str(override.get("temperature", "—")),
                str(override.get("seed", "—")),
                key=step_id,
            )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "llm-refresh":
            await self._refresh()


# ============================================================================
# Eval
# ============================================================================


class EvalScreen(Vertical):
    """List benchmark runs + quick judge launcher hint."""

    DEFAULT_CSS = """
    EvalScreen {
        padding: 1 2;
    }
    EvalScreen Horizontal.row {
        height: auto;
        margin-bottom: 1;
    }
    EvalScreen #eval-hint {
        padding: 1;
        border: solid $accent;
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "Launching runs is keyboard-driven from the CLI:\n"
            "  amber eval judge-run <dataset.jsonl> --judge-model ...\n"
            "  amber eval ragas-run <dataset.json>\n"
            "This screen polls the database and shows recent runs.",
            id="eval-hint",
        )
        with Horizontal(classes="row"):
            yield Button("Refresh", id="eval-refresh", variant="primary")
        yield DataTable(id="eval-runs", zebra_stripes=True, cursor_type="row")

    async def on_mount(self) -> None:
        table = self.query_one("#eval-runs", DataTable)
        table.add_columns("ID", "Framework", "Dataset", "Status", "Overall", "Created")
        await self._refresh()

    async def _refresh(self) -> None:
        rows = await tui_data.list_benchmark_runs(DEFAULT_TENANT)
        table = self.query_one("#eval-runs", DataTable)
        table.clear()
        for r in rows:
            overall = f"{float(r['overall']):.2f}" if isinstance(r["overall"], (int, float)) else "—"
            table.add_row(
                r["id"][:8],
                r["framework"],
                r["dataset"],
                r["status"],
                overall,
                r["created_at"],
                key=r["id"],
            )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "eval-refresh":
            await self._refresh()
